"""prepare_multi.py — HARNESS FIJO multi-activo (DIARIO). El agente NO edita este archivo.
Datos reales Yahoo: acciones (SPY, QQQ, GDX), oro (GLD, GC=F), plata (SLV, SI=F), crypto (BTC-USD).
Mismo contrato que prepare.py: strategy_multi.py define build_features/fit; walk-forward purgado
con embargo; targets dir/vol/exp; métricas BSS/AUC/ECE + skill vs HAR; backtest neto con costos
POR CLASE de activo; DSR; test PLACEBO (permuta señales por fecha: la real debe superarlo);
comparativa de rentabilidad por activo y clase (cuál es más rentable).

Uso:
  python multi/download_multi.py        # baja datos reales (una vez)
  python multi/prepare_multi.py dev     # evalúa strategy_multi.py en el 80% de desarrollo
  python multi/prepare_multi.py vault   # UNA vez sobre el 20% final
"""
import os, sys, time, json, math, importlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from prepare import brier, ece, auc, deflated_sharpe, LeakageError

RAW_PATH = os.path.join(HERE, "multi_raw.pkl")
UNIV_PATH = os.path.join(HERE, "multi_universe.csv")

HORIZONS = [1, 5, 10, 21]          # días de trading por símbolo
VOL_HORIZONS = [5, 10, 21]
EMBARGO = 25
VAULT_FRAC = 0.20
FOLD_DAYS = 126                    # bloque de test = ~6 meses
MIN_TRAIN_DAYS = 756               # 3 años de entrenamiento mínimo
TRAIN_STRIDE = int(os.environ.get("TRAIN_STRIDE", 1))
TOP_K = 2
CONF_MIN = 0.01
TIME_BUDGET = int(os.environ.get("TIME_BUDGET", 1200))
METRIC = os.environ.get("LOOP_METRIC", "all")
N_TRIALS = int(os.environ.get("VOL_N_TRIALS", 1))
ANN = 252.0
MIN_TRAIN_ROWS = 800
B2_TARGET = 0.15    # V5.1-B2: vol objetivo anual bruto (vol-targeting bruto)
B2_WINDOW = 21      # ventana trailing calendario (dias)
B2_MIN_SPAN = 15    # steps minimos para activar vol-targeting
B2_CLIP = 4.0       # clip de apalancamiento lambda [1/clip, clip]


def load_universe():
    u = pd.read_csv(UNIV_PATH)
    return (dict(zip(u.sym, u.asset_class)), dict(zip(u.sym, u.cost_bps)))


def load_panel():
    raw = pd.read_pickle(RAW_PATH)
    panel = raw.set_index(["sym", "ts"])[["open", "high", "low", "close", "volume", "turnover"]].sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    return panel


# ----------------------------------------------------------------------------- targets
def _roll(s, w, fn="sum"):
    return s.groupby(level="sym").transform(lambda x: getattr(x.rolling(w, min_periods=w), fn)())


def make_targets(panel):
    c = panel["close"]
    lc = np.log(c)
    g = lc.groupby(level="sym")
    rv1 = g.diff() ** 2
    tv63 = np.sqrt(_roll(rv1, 63) / 63)
    T = pd.DataFrame(index=panel.index)
    for h in HORIZONS:
        fr = g.shift(-h) - lc
        T[f"ret_{h}"] = fr
        T[f"dir_{h}"] = (fr > 0).astype(float).where(fr.notna())
    for h in VOL_HORIZONS:
        fv = np.sqrt(_roll(rv1, h).groupby(level="sym").shift(-h) / h)
        T[f"vol_{h}"] = np.log(fv + 1e-6)
        T[f"exp_{h}"] = (fv > tv63).astype(float).where(fv.notna() & tv63.notna())
    return T


def har_features(panel):
    """Baseline HAR-RV diario (Corsi): 5/21/63 días. Fijo, no editable."""
    rv1 = np.log(panel["close"]).groupby(level="sym").diff() ** 2
    H = pd.DataFrame(index=panel.index)
    for w in (5, 21, 63):
        H[f"har_{w}"] = np.log(np.sqrt(_roll(rv1, w) / w) + 1e-6)
    return H

# ----------------------------------------------------------------------------- backtests
def backtest_ls(p, r, ts, sym, cost, h):
    """Cross-sectional L/S neutral: top-K vs bottom-K por p, con umbral, costos POR símbolo."""
    d = pd.DataFrame({"p": p, "r": r, "tt": ts, "sym": sym, "cost": cost}).dropna()
    # V5.1-B2 [out-of-rieles, auth 09-Oct]: vol-targeting BRUTO (causal). Preserva
    # el cross-section equal-weight (EW gana holdout) y escala exposicion bruta a
    # vol objetivo anual B2_TARGET, down-scaling en crisis (regimen-robusto). No toca forecast.
    net, gross, idx = [], [], []
    prev = pd.Series(dtype=float)
    gp_hist = []
    tv_step = B2_TARGET / math.sqrt(ANN / h)
    wv_vt = max(B2_MIN_SPAN, int(B2_WINDOW / h))
    for t, g in d.groupby("tt"):
        g = g.sort_values("p")
        conf = g["p"] - 0.5
        shorts = g[conf <= -CONF_MIN].head(TOP_K)
        longs = g[conf >= CONF_MIN].tail(TOP_K)
        if len(longs) == 0 or len(shorts) == 0:   # neutralidad: sin ambos lados no se opera
            prev = pd.Series(dtype=float)
            net.append(0.0); gross.append(0.0); idx.append(t); gp_hist.append(0.0)
            continue
        w = pd.Series(dtype=float)
        w = pd.concat([w, pd.Series(0.5 / len(longs), index=longs["sym"].values)])
        w = pd.concat([w, pd.Series(-0.5 / len(shorts), index=shorts["sym"].values)])
        allidx = prev.index.union(w.index)
        dw = (w.reindex(allidx).fillna(0) - prev.reindex(allidx).fillna(0)).abs()
        wv = w.reindex(allidx).fillna(0)
        gp = float((wv * g.set_index("sym")["r"].reindex(allidx).fillna(0)).sum())
        cc = float((dw * g.set_index("sym")["cost"].reindex(allidx).fillna(0)).sum()) / 1e4
        if len(gp_hist) >= wv_vt:
            sig = pd.Series(gp_hist[-wv_vt:]).std()
            lam = (tv_step / (sig + 1e-9)) if (np.isfinite(sig) and sig > 0) else 1.0
            lam = min(max(lam, 1.0 / B2_CLIP), B2_CLIP)
        else:
            lam = 1.0
        gp_hist.append(gp)
        net.append(lam * (gp - cc)); gross.append(lam * gp); idx.append(t)
        prev = w
    net = pd.Series(net, index=idx); gross = pd.Series(gross, index=idx)
    ann = math.sqrt(ANN / h)
    sd = net.std()
    out = dict(n=len(net), net_sharpe=float(net.mean() / sd * ann) if sd and sd > 0 else 0.0,
               gross_sharpe=float(gross.mean() / gross.std() * ann) if gross.std() > 0 else 0.0,
               net_bps=float(net.mean() * 1e4))
    return out, net


def backtest_asset(p, r, cost, h):
    """Single-asset L/S por signo de (p-0.5) con umbral; coste solo al girar posición."""
    d = pd.DataFrame({"p": p, "r": r}).dropna()
    if len(d) < 30:
        return dict(n=0, net_sharpe=0.0, net_bps=0.0)
    pos = pd.Series(np.where(d["p"] > 0.5 + CONF_MIN, 1.0, np.where(d["p"] < 0.5 - CONF_MIN, -1.0, 0.0)),
                    index=d.index)
    dpos = pos.diff().abs()
    dpos.iloc[0] = abs(pos.iloc[0])
    net = pos * d["r"] - dpos.fillna(0.0) * cost / 1e4
    ann = math.sqrt(ANN / h)
    sd = net.std()
    return dict(n=int(len(net)), net_sharpe=float(net.mean() / sd * ann) if sd and sd > 0 else 0.0,
                net_bps=float(net.mean() * 1e4))


# ----------------------------------------------------------------------------- causalidad
def check_causal(S, panel):
    """Recalcula features con datos truncados; si cambian valores pasados => leakage => error."""
    ts = panel.index.get_level_values("ts")
    tmax = ts.max()
    P = panel[ts >= tmax - pd.Timedelta(days=400)]
    cut = tmax - pd.Timedelta(days=30)
    Pc = P[P.index.get_level_values("ts") <= cut]
    F, Fc = S.build_features(P), S.build_features(Pc)
    F = F.loc[Fc.index]
    bad = [c for c in Fc.columns
           if not np.allclose(F[c].to_numpy(float), Fc[c].to_numpy(float), rtol=1e-4, atol=1e-6, equal_nan=True)]
    if bad:
        raise LeakageError(f"Features NO causales (cambian al truncar el futuro): {bad}")


# ----------------------------------------------------------------------------- evaluación
def evaluate(mode="dev", verbose=True):
    t0 = time.time()
    S = importlib.import_module("strategy_multi")
    cls_map, cost_map = load_universe()
    panel_all = load_panel()
    ts_all = panel_all.index.get_level_values("ts")
    uts = np.sort(ts_all.unique())
    cut = uts[int(len(uts) * (1 - VAULT_FRAC))]
    panel = panel_all[ts_all < cut] if mode == "dev" else panel_all
    check_causal(S, panel)
    feats = S.build_features(panel)
    if not feats.index.equals(panel.index):
        raise ValueError("build_features debe devolver el mismo índice que el panel")
    T = make_targets(panel)
    Hf = har_features(panel)

    ts = panel.index.get_level_values("ts")
    syms = panel.index.get_level_values("sym")
    costs = pd.Series(syms).map(cost_map).to_numpy()
    tmin = np.datetime64(ts.min(), "D")
    hidx = ((ts.values.astype("datetime64[D]") - tmin).astype("timedelta64[D]").astype(np.int64))
    cut_d = int((np.datetime64(cut, "D") - tmin).astype("timedelta64[D]").astype(np.int64))
    first = MIN_TRAIN_DAYS if mode == "dev" else cut_d
    last = int(hidx.max())
    starts = list(range(first, last - 5, FOLD_DAYS))

    tasks = [("dir", h) for h in HORIZONS] + [("vol", h) for h in VOL_HORIZONS] + [("exp", h) for h in VOL_HORIZONS]
    pred = {k: np.full(len(panel), np.nan) for k in tasks}
    base = {k: np.full(len(panel), np.nan) for k in tasks}
    har = {h: np.full(len(panel), np.nan) for h in VOL_HORIZONS}
    tested = np.zeros(len(panel), bool)

    for fi, s in enumerate(starts):
        te = np.where((hidx >= s) & (hidx < s + FOLD_DAYS))[0]
        tr = np.where((hidx < s - EMBARGO) & (hidx % TRAIN_STRIDE == 0))[0]
        tr = tr[np.argsort(hidx[tr], kind="stable")]
        if len(te) == 0 or len(tr) < MIN_TRAIN_ROWS:
            continue
        tested[te] = True
        Xtr, Xte = feats.iloc[tr], feats.iloc[te]
        for (task, h) in tasks:
            if time.time() - t0 > TIME_BUDGET:
                raise TimeoutError(f"excedió TIME_BUDGET={TIME_BUDGET}s")
            y = T[f"{task}_{h}"].iloc[tr]
            ok = y.notna().values
            m = S.fit(Xtr[ok], y[ok], task, h)
            pred[(task, h)][te] = m.predict(Xte)
            base[(task, h)][te] = y[ok].mean()
            if task == "vol":                                     # HAR OLS por fold
                A = np.c_[np.ones(int(ok.sum())), Hf.iloc[tr][ok].to_numpy()]
                good = np.isfinite(A).all(1)
                if good.sum() >= 10:
                    beta = np.linalg.lstsq(A[good], y[ok].to_numpy()[good], rcond=None)[0]
                    har[h][te] = np.c_[np.ones(len(te)), Hf.iloc[te].to_numpy()] @ beta
        if verbose:
            print(f"  fold {fi + 1}/{len(starts)} listo ({time.time() - t0:.0f}s)", flush=True)

    res = {"mode": mode, "n_folds": len(starts), "dir": {}, "vol": {}, "exp": {}, "bt": {}, "asset": {}}
    for h in HORIZONS:
        p, y = pred[("dir", h)], T[f"dir_{h}"].to_numpy()
        m = tested & np.isfinite(p) & np.isfinite(y)
        res["dir"][h] = dict(bss=1 - brier(p[m], y[m]) / brier(base[("dir", h)][m], y[m]),
                             auc=auc(p[m], y[m]), ece=ece(p[m], y[m]), acc=float(((p[m] > .5) == (y[m] > .5)).mean()))
    for h in VOL_HORIZONS:
        p, y = pred[("vol", h)], T[f"vol_{h}"].to_numpy()
        m = tested & np.isfinite(p) & np.isfinite(y) & np.isfinite(har[h])
        mse_m, mse_h = np.mean((p[m] - y[m]) ** 2), np.mean((har[h][m] - y[m]) ** 2)
        mse_b = np.mean((base[("vol", h)][m] - y[m]) ** 2)
        res["vol"][h] = dict(r2=1 - mse_m / mse_b, skill_vs_har=1 - mse_m / mse_h, har_r2=1 - mse_h / mse_b)
        p2, y2 = pred[("exp", h)], T[f"exp_{h}"].to_numpy()
        m2 = tested & np.isfinite(p2) & np.isfinite(y2)
        res["exp"][h] = dict(bss=1 - brier(p2[m2], y2[m2]) / brier(base[("exp", h)][m2], y2[m2]),
                             auc=auc(p2[m2], y2[m2]), ece=ece(p2[m2], y2[m2]))

    placebo_best = 0.0
    for h in HORIZONS:
        r = T[f"ret_{h}"].to_numpy()
        p = pred[("dir", h)]
        m = tested & (hidx % h == 0) & np.isfinite(p) & np.isfinite(r)
        bt, net = backtest_ls(p[m], r[m], ts[m], syms[m], costs[m], h)
        bt["dsr"] = deflated_sharpe(net, N_TRIALS * len(HORIZONS))
        res["bt"][h] = bt
        d = pd.DataFrame({"p": p[m], "r": r[m], "sym": syms[m]})
        for sym, gsy in d.groupby("sym"):
            res["asset"].setdefault(sym, {})[h] = backtest_asset(gsy["p"].to_numpy(), gsy["r"].to_numpy(),
                                                                 cost_map[sym], h)
        shs = []
        tt_m = ts[m]
        codes, uniq = pd.factorize(tt_m)
        for sd_ in range(6):
            rng = np.random.default_rng(sd_)
            pp = p[m].copy()
            for c in range(len(uniq)):                     # permuta intra-fecha (numpy puro; el
                idx = np.where(codes == c)[0]              # transform de pandas 3.0 rompe arrays)
                pp[idx] = rng.permutation(pp[idx])
            bt_p, _ = backtest_ls(pp, r[m], ts[m], syms[m], costs[m], h)
            shs.append(bt_p["net_sharpe"])
        shs = np.array(shs)
        res.setdefault("placebo", {})[h] = dict(mean=float(shs.mean()), sd=float(shs.std()), max=float(shs.max()))
        # benchmark ESTATICO: ranking fijo de syms (sin info) — el real debe superarlo
        sym_rank = pd.Series(np.asarray(syms[m])).map({s: i for i, s in enumerate(sorted(set(np.asarray(syms))))}).to_numpy()
        p_static = 0.5 + 0.02 * sym_rank
        bt_s, _ = backtest_ls(p_static, r[m], ts[m], syms[m], costs[m], h)
        res.setdefault("static", {})[h] = bt_s["net_sharpe"]
        placebo_best = max(placebo_best, max(shs.mean() + 2 * shs.std(), bt_s["net_sharpe"]))

    asset_best = {sym: max(v.values(), key=lambda x: x["net_sharpe"]) for sym, v in res["asset"].items()}
    res["asset_best"] = asset_best
    by_class = {}
    for sym, v in asset_best.items():
        by_class.setdefault(cls_map[sym], []).append(v["net_sharpe"])
    res["class_best_sharpe"] = {k: float(np.mean(v)) for k, v in by_class.items()}

    vs = float(np.mean([res["vol"][h]["skill_vs_har"] for h in VOL_HORIZONS]))
    eb = float(np.mean([res["exp"][h]["bss"] for h in VOL_HORIZONS]))
    db = float(np.mean([res["dir"][h]["bss"] for h in HORIZONS]))
    res["summary"] = dict(vol_skill=vs, exp_bss=eb, dir_bss=db,
                          best_net_sharpe=max(v["net_sharpe"] for v in res["bt"].values()),
                          placebo_best_sharpe=float(placebo_best),
                          class_best_sharpe=res["class_best_sharpe"],
                          score={"vol": vs + eb, "dir": db, "all": vs + eb + db}[METRIC],
                          seconds=time.time() - t0, n_trials=N_TRIALS)
    res["gates"] = gates(res)
    return res


def gates(res):
    pb = res["summary"]["placebo_best_sharpe"]
    rb = max(res["summary"]["best_net_sharpe"], 0.0)
    return {
        "vol_gana_a_HAR_en_>=2_de_3_horizontes": sum(res["vol"][h]["skill_vs_har"] > 0 for h in VOL_HORIZONS) >= 2,
        "expansion_vol_BSS>0_en_>=2_de_3": sum(res["exp"][h]["bss"] > 0 for h in VOL_HORIZONS) >= 2,
        "calibracion_ECE<0.03_en_exp_y_dir": all(res["exp"][h]["ece"] < 0.03 for h in VOL_HORIZONS)
                                              and all(res["dir"][h]["ece"] < 0.03 for h in HORIZONS),
        "direccion_BSS>0_en_>=2_de_4": sum(res["dir"][h]["bss"] > 0 for h in HORIZONS) >= 2,
        "backtest_neto_Sharpe>0_y_DSR>0.95_en_algun_h": any(v["net_sharpe"] > 0 and (v["dsr"] or 0) > 0.95
                                                             for v in res["bt"].values()),
        "placebo_no_rentable": (pb < rb) and (pb < 0.5),
    }


def report(res):
    print(f"\n=== MULTI {res['mode'].upper()} | folds={res['n_folds']} | {res['summary']['seconds']:.0f}s ===")
    print("DIRECCION      d    BSS      AUC     ECE     acc")
    for h, v in res["dir"].items():
        print(f"               {h:>2}  {v['bss']:+.4f}  {v['auc']:.4f}  {v['ece']:.4f}  {v['acc']:.4f}")
    print("VOLATILIDAD    d    R2       HAR_R2   skill_vs_HAR   | expansion: BSS    AUC    ECE")
    for h in VOL_HORIZONS:
        v, e = res["vol"][h], res["exp"][h]
        print(f"               {h:>2}  {v['r2']:.4f}  {v['har_r2']:.4f}   {v['skill_vs_har']:+.4f}       |            "
              f"{e['bss']:+.4f}  {e['auc']:.4f} {e['ece']:.4f}")
    print("BACKTEST L/S cross-secc neto  d    n    netSharpe  grossSharpe  net_bps   DSR")
    for h, v in res["bt"].items():
        print(f"                                   {h:>2}  {v['n']:>5}  {v['net_sharpe']:+.2f}      {v['gross_sharpe']:+.2f}"
              f"        {v['net_bps']:+.2f}    {v['dsr']:.3f}")
    print("COMPARATIVA POR ACTIVO (mejor horizonte, L/S single-asset neto):")
    for sym, v in sorted(res["asset_best"].items(), key=lambda kv: -kv[1]["net_sharpe"]):
        print(f"    {sym:8s} n={v['n']:>5}  netSharpe={v['net_sharpe']:+.2f}  net_bps={v['net_bps']:+.2f}")
    print("POR CLASE (media del mejor Sharpe):")
    for k, v in sorted(res["class_best_sharpe"].items(), key=lambda kv: -kv[1]):
        print(f"    {k:20s} {v:+.2f}")
    print("PLACEBO por h (media+-sd, max):")
    for h, v in res.get("placebo", {}).items():
        print(f"    h={h:>2}: {v['mean']:+.2f} +- {v['sd']:.2f}  max={v['max']:+.2f}")
    print("GATES:")
    for k, ok in res["gates"].items():
        print(f"  [{'OK' if ok else '--'}] {k}")
    print("SUMMARY_JSON:" + json.dumps(res["summary"]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if cmd == "download":
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "download_multi.py")], check=True)
    else:
        r = evaluate(cmd)
        report(r)
        with open(os.path.join(HERE, f"report_{cmd}.json"), "w") as f:
            json.dump(r, f, indent=1, default=str)

