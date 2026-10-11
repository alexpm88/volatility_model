"""
live.py — Puesta en vivo (PAPER por defecto) con la mejor strategy.py validada.
  python live.py train      # entrena modelos finales con TODO el histórico y los guarda (models.pkl)
  python live.py run        # loop horario: velas cerradas -> features -> predicciones calibradas -> señales
Incluye: gating por confianza, monitor de drift (Brier rodante vs tasa base) con kill-switch, re-entreno semanal.
La ejecución real NO está conectada a propósito: enchufa tu cliente KuCoin en `execute()` (ver abajo).
"""
import os, sys, time, json, pickle
import numpy as np, pandas as pd
import prepare as P
import strategy as S

MODELS, SIGNALS, RESOLVED, STATE = "models.pkl", "signals.csv", "resolved.csv", "state.json"
LIVE_HOURS = 900            # >= 720 (rv_720) + margen; una sola llamada de 1500 velas por símbolo
RETRAIN_EVERY_H = 168
MON_WINDOW, MON_MIN = 400, 100   # nº de predicciones resueltas para evaluar drift
CONF_GATE = P.CONF_MIN


def train():
    panel = P.load_panel()
    feats, T = S.build_features(panel), P.make_targets(panel)
    ts = panel.index.get_level_values("ts")
    hidx = ((ts.values.astype("datetime64[h]") - ts.values.astype("datetime64[h]").min()).astype("timedelta64[h]").astype(np.int64))
    tr = np.where(hidx % P.TRAIN_STRIDE == 0)[0]
    tr = tr[np.argsort(hidx[tr], kind="stable")]
    models = {}
    tasks = [("dir", h) for h in P.HORIZONS] + [("vol", h) for h in P.VOL_HORIZONS] + [("exp", h) for h in P.VOL_HORIZONS]
    for task, h in tasks:
        y = T[f"{task}_{h}"].iloc[tr]; ok = y.notna().values
        models[(task, h)] = S.fit(feats.iloc[tr][ok], y[ok], task, h)
        print("entrenado", task, h)
    base = {k: float(T[f"{k[0]}_{k[1]}"].mean()) for k in models if k[0] != "vol"}
    pickle.dump(dict(models=models, base=base, trained_at=time.time(), cols=list(feats.columns)), open(MODELS, "wb"))


def latest_panel():
    uni = pd.read_csv(P.UNIV_PATH).symbol.tolist()
    start = int(time.time()) - LIVE_HOURS * 3600
    frames = [P.fetch_candles(s, start) for s in uni]
    raw = pd.concat([f for f in frames if len(f)], ignore_index=True)
    panel = P.raw_to_panel(raw)
    now_h = pd.Timestamp.utcnow().tz_localize(None).floor("h")
    ts = panel.index.get_level_values("ts")
    return panel[ts < now_h]                     # descarta la vela en formación: solo velas CERRADAS


def score_now(bundle):
    panel = latest_panel()
    feats = S.build_features(panel)
    tmax = feats.index.get_level_values("ts").max()
    X = feats[feats.index.get_level_values("ts") == tmax].dropna(how="all")
    rows = []
    for (task, h), m in bundle["models"].items():
        pr = m.predict(X)
        for (sym, ts), v in zip(X.index, pr):
            rows.append(dict(ts=ts, sym=sym, task=task, h=h, pred=float(v), close=float(panel.loc[(sym, ts), "close"])))
    return pd.DataFrame(rows), tmax


def targets_from(sig, tmax):
    """Pesos L/S neutral (top-K vs bottom-K) para los horizontes cuyo reloj toca ahora."""
    hour = int(tmax.value // 3_600_000_000_000)
    out = {}
    for h in P.HORIZONS:
        if hour % h:
            continue
        d = sig[(sig.task == "dir") & (sig.h == h)].set_index("sym")["pred"] - 0.5
        longs, shorts = d[d >= CONF_GATE].nlargest(P.TOP_K), d[d <= -CONF_GATE].nsmallest(P.TOP_K)
        w = {**{s: 0.5 / len(longs) for s in longs.index}, **{s: -0.5 / len(shorts) for s in shorts.index}} if (len(longs) or len(shorts)) else {}
        out[h] = w
    return out


def execute(targets, killed):
    """PUNTO DE ENGANCHE: aquí conecta tu cliente KuCoin Futures (firmado) y envía órdenes limit/post-only.
    Por defecto solo imprime (paper). Con killed=True NO se debe abrir nada nuevo (solo cerrar)."""
    for h, w in targets.items():
        print(f"  [PAPER] h={h}h  {'(KILL-SWITCH: no abrir)' if killed else ''} {json.dumps({k: round(v, 3) for k, v in w.items()})}")


def resolve(all_sig, panel_close):
    """Cuando ya pasaron h horas, compara predicción vs realidad y guarda Brier/error."""
    if not os.path.exists(SIGNALS):
        return
    s = pd.read_csv(SIGNALS, parse_dates=["ts"])
    done = set(pd.read_csv(RESOLVED, parse_dates=["ts"]).apply(lambda r: (r.ts, r.sym, r.task, r.h), axis=1)) if os.path.exists(RESOLVED) else set()
    out, tmax = [], panel_close.index.get_level_values("ts").max()
    for r in s.itertuples():
        if (r.ts, r.sym, r.task, r.h) in done or r.ts + pd.Timedelta(hours=int(r.h)) > tmax:
            continue
        try:
            c1 = panel_close.loc[(r.sym, r.ts + pd.Timedelta(hours=int(r.h)))]
        except KeyError:
            continue
        ret = np.log(c1 / r.close)
        if r.task == "dir":
            out.append((r.ts, r.sym, r.task, r.h, r.pred, float(ret > 0)))
    if out:
        pd.DataFrame(out, columns=["ts", "sym", "task", "h", "pred", "y"]).to_csv(RESOLVED, mode="a", header=not os.path.exists(RESOLVED), index=False)


def monitor(bundle):
    """Kill-switch: si el Brier rodante de dirección es peor que la tasa base => modelo sin edge => flat."""
    if not os.path.exists(RESOLVED):
        return False, {}
    r = pd.read_csv(RESOLVED).tail(MON_WINDOW * 5)
    st = {}
    for h, g in r.groupby("h"):
        g = g.tail(MON_WINDOW)
        if len(g) >= MON_MIN:
            b0 = bundle["base"].get(("dir", int(h)), 0.5)
            st[int(h)] = 1 - np.mean((g.pred - g.y) ** 2) / np.mean((b0 - g.y) ** 2)   # BSS rodante
    killed = bool(st) and np.mean(list(st.values())) < 0
    return killed, st


def run():
    bundle = pickle.load(open(MODELS, "rb"))
    while True:
        nxt = (pd.Timestamp.utcnow().tz_localize(None).floor("h") + pd.Timedelta(hours=1, seconds=25))
        time.sleep(max(0, (nxt - pd.Timestamp.utcnow().tz_localize(None)).total_seconds()))
        try:
            sig, tmax = score_now(bundle)
            sig.to_csv(SIGNALS, mode="a", header=not os.path.exists(SIGNALS), index=False)
            resolve(sig, latest_panel()["close"])
            killed, st = monitor(bundle)
            print(f"{tmax}  BSS rodante por h: { {k: round(v, 4) for k, v in st.items()} }  kill={killed}")
            vol = sig[(sig.task == 'exp') & (sig.h == 24)].pred.describe()[["mean", "max"]].round(3).to_dict()
            print("  P(expansión vol 24h) mercado:", vol)   # útil para dimensionar riesgo / sizing por régimen
            execute(targets_from(sig, tmax), killed)
            if time.time() - bundle["trained_at"] > RETRAIN_EVERY_H * 3600:
                print("re-entrenando..."); train(); bundle = pickle.load(open(MODELS, "rb"))
        except Exception as e:
            print("ERROR en ciclo (se reintenta la próxima hora):", repr(e))


if __name__ == "__main__":
    {"train": train, "run": run}[sys.argv[1]]()
