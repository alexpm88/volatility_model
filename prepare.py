"""
prepare.py — HARNESS FIJO. El agente / tú NO editas este archivo durante el loop.
Datos KuCoin H1 (top-50), targets 1/4/8/12/24h, walk-forward purgado con embargo,
métricas (Brier/AUC/ECE, skill vs HAR-RV), backtest neto de costos, DSR, vault final.

Uso:
  python prepare.py download [dias]   # baja universo + velas H1 de KuCoin
  python prepare.py dev               # evalúa strategy.py en el 80% de desarrollo
  python prepare.py vault             # evalúa UNA vez en el 20% final (vault)
"""
import os, sys, time, json, math, importlib
import numpy as np
import pandas as pd

DATA_DIR = os.environ.get("VOL_DATA", "data")
RAW_PATH = os.path.join(DATA_DIR, "raw_h1.pkl")
UNIV_PATH = os.path.join(DATA_DIR, "universe.csv")

HORIZONS = [1, 4, 8, 12, 24]
VOL_HORIZONS = [4, 8, 12, 24]
EMBARGO = 24                      # horas: >= max horizonte (evita solape train/test)
VAULT_FRAC = 0.20                 # último 20% del tiempo = vault (no se toca en el loop)
FOLD_HOURS = 30 * 24              # bloque de test = 30 días
MIN_TRAIN_HOURS = 180 * 24
TRAIN_STRIDE = int(os.environ.get("TRAIN_STRIDE", 3))   # submuestreo de train (labels solapados)
COST_BPS = float(os.environ.get("COST_BPS", 10.0))      # por lado (taker spot KuCoin ~10 bps)
TOP_K = 5
CONF_MIN = 0.01                   # |p-0.5| mínimo para operar
TIME_BUDGET = int(os.environ.get("TIME_BUDGET", 1500))  # segundos por evaluación
METRIC = os.environ.get("LOOP_METRIC", "vol")           # vol | dir | all
N_TRIALS = int(os.environ.get("VOL_N_TRIALS", 1))       # para Deflated Sharpe

# ----------------------------------------------------------------------------- KuCoin
STABLES = {"USDC", "TUSD", "DAI", "USDD", "FDUSD", "PYUSD", "USDP", "EURC", "USDE", "BUSD", "UST"}


def _get(path, params=None):
    import requests
    last = None
    for i in range(6):
        try:
            r = requests.get("https://api.kucoin.com" + path, params=params, timeout=20)
            j = r.json()
            if j.get("code") == "200000":
                return j["data"]
            last = j
        except Exception as e:  # noqa
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"KuCoin API error en {path}: {last}")


def build_universe(n=50):
    """Top-n USDT por volumen 24h de KuCoin (+ market cap de CoinGecko si hay red)."""
    t = pd.DataFrame(_get("/api/v1/market/allTickers")["ticker"])
    t = t[t.symbol.str.endswith("-USDT")].copy()
    t["base"] = t.symbol.str.replace("-USDT", "", regex=False)
    t = t[~t.base.isin(STABLES) & ~t.base.str.contains(r"(?:3L|3S|5L|5S)$")]
    t["vol_usd"] = pd.to_numeric(t["volValue"], errors="coerce")
    t = t.dropna(subset=["vol_usd"])
    try:
        import requests
        caps = {}
        for page in (1, 2):
            r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                             params=dict(vs_currency="usd", order="market_cap_desc", per_page=250, page=page),
                             timeout=30).json()
            for c in r:
                caps.setdefault(c["symbol"].upper(), c["market_cap"])   # ticker duplicado: gana el de mayor cap
        t["mcap"] = t.base.map(caps)
    except Exception:
        t["mcap"] = np.nan
    t["r_vol"] = t.vol_usd.rank(ascending=False)
    t["r_cap"] = t.mcap.rank(ascending=False)
    t["score"] = t[["r_vol", "r_cap"]].mean(axis=1, skipna=True)
    t = t.sort_values("score").head(int(n * 1.5))
    return t[["symbol", "base", "vol_usd", "mcap", "score"]].reset_index(drop=True)


def fetch_candles(sym, start_ts, end_ts=None):
    end = int(end_ts or time.time())
    rows = []
    while end > start_ts:
        st = max(start_ts, end - 1500 * 3600)
        d = _get("/api/v1/market/candles", dict(type="1hour", symbol=sym, startAt=st, endAt=end))
        if not d:
            break
        rows += d
        oldest = min(int(x[0]) for x in d)
        if oldest <= start_ts or oldest >= end:
            break
        end = oldest
        time.sleep(0.12)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
    df = df.astype({"time": "int64", "open": float, "close": float, "high": float, "low": float,
                    "volume": float, "turnover": float})
    df["sym"] = sym
    return df.drop_duplicates("time").sort_values("time")


def download(days=730, n=50):
    os.makedirs(DATA_DIR, exist_ok=True)
    uni = build_universe(n)
    start = int(time.time()) - days * 86400
    frames, kept = [], []
    for sym in uni.symbol:
        df = fetch_candles(sym, start)
        if len(df) >= 24 * 120:                       # >= 120 días de historia
            frames.append(df); kept.append(sym)
            print(f"[{len(kept):2d}/{n}] {sym}: {len(df)} velas")
        if len(kept) >= n:
            break
    raw = pd.concat(frames, ignore_index=True)
    raw.to_pickle(RAW_PATH)
    uni[uni.symbol.isin(kept)].to_csv(UNIV_PATH, index=False)
    print("guardado", RAW_PATH, raw.shape)


def raw_to_panel(raw):
    """Long crudo -> panel MultiIndex (sym, ts) con grilla horaria regular por símbolo."""
    raw = raw.copy()
    raw["ts"] = pd.to_datetime(raw["time"].astype("int64"), unit="s").dt.floor("h")
    raw = raw.drop_duplicates(["sym", "ts"])
    grid = pd.date_range(raw.ts.min(), raw.ts.max(), freq="h")
    parts = {}
    for sym in sorted(raw.sym.unique()):
        d = raw[raw.sym == sym].set_index("ts").reindex(grid)
        c = d["close"].ffill(limit=6)
        df = pd.DataFrame({
            "open": d["open"].fillna(c), "high": d["high"].fillna(c), "low": d["low"].fillna(c), "close": c,
            "volume": d["volume"].fillna(0.0).where(c.notna()),
            "turnover": d["turnover"].fillna(0.0).where(c.notna()),
        })
        first = df["close"].first_valid_index()
        if first is not None:
            parts[sym] = df.loc[first:]
    panel = pd.concat(parts, names=["sym", "ts"])
    return panel.sort_index()


def load_panel():
    return raw_to_panel(pd.read_pickle(RAW_PATH))


# ----------------------------------------------------------------------------- targets
def _roll(s, w, fn="sum"):
    return s.groupby(level="sym").transform(lambda x: getattr(x.rolling(w, min_periods=w), fn)())


def make_targets(panel):
    c = panel["close"]
    lc = np.log(c)
    g = lc.groupby(level="sym")
    rv1 = g.diff() ** 2
    T = pd.DataFrame(index=panel.index)
    tv168 = np.sqrt(_roll(rv1, 168) / 168)                        # vol horaria de la última semana (en t)
    for h in HORIZONS:
        fr = g.shift(-h) - lc
        T[f"ret_{h}"] = fr
        T[f"dir_{h}"] = (fr > 0).astype(float).where(fr.notna())
    for h in VOL_HORIZONS:
        fv = np.sqrt(_roll(rv1, h).groupby(level="sym").shift(-h) / h)   # vol horaria en (t, t+h]
        T[f"vol_{h}"] = np.log(fv + 1e-6)
        T[f"exp_{h}"] = (fv > tv168).astype(float).where(fv.notna() & tv168.notna())  # expansión de vol
    return T


def har_features(panel):
    """Baseline HAR-RV (Corsi): log vol horaria en ventanas 24h/168h/720h. Fijo, no editable."""
    rv1 = np.log(panel["close"]).groupby(level="sym").diff() ** 2
    H = pd.DataFrame(index=panel.index)
    for w in (24, 168, 720):
        H[f"har_{w}"] = np.log(np.sqrt(_roll(rv1, w) / w) + 1e-6)
    return H


# ----------------------------------------------------------------------------- métricas
def brier(p, y):
    return float(np.mean((p - y) ** 2))


def ece(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    e = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)


def auc(p, y):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else float("nan")


def backtest(p, r, ts, h):
    """Long/short cross-sectional neutral: top-K vs bottom-K por p, con umbral de confianza y costos."""
    d = pd.DataFrame({"p": p, "r": r, "tt": ts}).dropna()
    d["sym"] = d.index.get_level_values("sym") if isinstance(d.index, pd.MultiIndex) else d.index
    net, gross, turn, idx = [], [], [], []
    prev = pd.Series(dtype=float)
    for t, g in d.groupby("tt"):
        g = g.sort_values("p")
        conf = g["p"] - 0.5
        shorts = g[conf <= -CONF_MIN].head(TOP_K)
        longs = g[conf >= CONF_MIN].tail(TOP_K)
        if len(longs) == 0 or len(shorts) == 0:   # neutralidad: sin ambos lados no se opera
            prev = pd.Series(dtype=float)
            net.append(0.0); gross.append(0.0); turn.append(float(prev.abs().sum())); idx.append(t)
            continue
        w = pd.Series(dtype=float)
        w = pd.concat([w, pd.Series(0.5 / len(longs), index=longs["sym"].values)])
        w = pd.concat([w, pd.Series(-0.5 / len(shorts), index=shorts["sym"].values)])
        allidx = prev.index.union(w.index)
        tv = float((w.reindex(allidx).fillna(0) - prev.reindex(allidx).fillna(0)).abs().sum())
        rr = g.set_index("sym")["r"]
        gp = float((w * rr.reindex(w.index)).sum()) if len(w) else 0.0
        gross.append(gp); turn.append(tv); net.append(gp - tv * COST_BPS / 1e4); idx.append(t)
        prev = w
    net = pd.Series(net, index=idx); gross = pd.Series(gross, index=idx)
    ann = math.sqrt(8760 / h)
    sd = net.std()
    out = dict(n=len(net), net_sharpe=float(net.mean() / sd * ann) if sd and sd > 0 else 0.0,
               gross_sharpe=float(gross.mean() / gross.std() * ann) if gross.std() > 0 else 0.0,
               net_bps=float(net.mean() * 1e4), turnover=float(np.mean(turn)) if turn else 0.0)
    return out, net


def deflated_sharpe(net, n_trials):
    """Bailey & López de Prado (2014), aproximado: prob. de que el Sharpe verdadero > 0 tras n_trials."""
    from scipy.stats import norm, skew, kurtosis
    x = net.values
    T = len(x)
    if T < 30 or x.std() == 0:
        return float("nan")
    sr = x.mean() / x.std()
    sk, ku = skew(x), kurtosis(x, fisher=False)
    var_sr = (1 - sk * sr + (ku - 1) / 4 * sr ** 2) / (T - 1)
    g = 0.5772156649
    N = max(n_trials, 1)
    sr0 = math.sqrt(var_sr) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * math.e))) if N > 1 else 0.0
    return float(norm.cdf((sr - sr0) / math.sqrt(var_sr)))


# ----------------------------------------------------------------------------- causalidad
class LeakageError(Exception):
    pass


def check_causal(S, panel):
    """Recalcula features con datos truncados; si cambian valores pasados => mira al futuro => error."""
    ts = panel.index.get_level_values("ts")
    tmax = ts.max()
    P = panel[ts >= tmax - pd.Timedelta(hours=2600)]
    cut = tmax - pd.Timedelta(hours=600)
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
    S = importlib.import_module("strategy")
    panel_all = load_panel()
    ts_all = panel_all.index.get_level_values("ts")
    uts = np.sort(ts_all.unique())
    cut = uts[int(len(uts) * (1 - VAULT_FRAC))]
    panel = panel_all[ts_all < cut] if mode == "dev" else panel_all      # dev: el vault ni existe
    check_causal(S, panel)
    feats = S.build_features(panel)
    if not feats.index.equals(panel.index):
        raise ValueError("build_features debe devolver el mismo índice que el panel")
    T = make_targets(panel)
    Hf = har_features(panel)

    ts = panel.index.get_level_values("ts")
    hidx = ((ts.values.astype("datetime64[h]") - ts.values.astype("datetime64[h]").min())
            .astype("timedelta64[h]").astype(np.int64))
    cut_h = int(((np.datetime64(cut, "h") - ts.values.astype("datetime64[h]").min()).astype("timedelta64[h]")).astype(np.int64))
    first = MIN_TRAIN_HOURS if mode == "dev" else cut_h
    last = int(hidx.max())
    starts = list(range(first, last - 24, FOLD_HOURS))

    tasks = [("dir", h) for h in HORIZONS] + [("vol", h) for h in VOL_HORIZONS] + [("exp", h) for h in VOL_HORIZONS]
    pred = {k: np.full(len(panel), np.nan) for k in tasks}
    base = {k: np.full(len(panel), np.nan) for k in tasks}
    har = {h: np.full(len(panel), np.nan) for h in VOL_HORIZONS}
    tested = np.zeros(len(panel), bool)

    for fi, s in enumerate(starts):
        te = np.where((hidx >= s) & (hidx < s + FOLD_HOURS))[0]
        tr = np.where((hidx < s - EMBARGO) & (hidx % TRAIN_STRIDE == 0))[0]
        tr = tr[np.argsort(hidx[tr], kind="stable")]                      # train en orden cronológico
        if len(te) == 0 or len(tr) < 5000:
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
            if task == "vol":                                             # HAR OLS por fold
                A = np.c_[np.ones(ok.sum()), Hf.iloc[tr][ok].to_numpy()]
                good = np.isfinite(A).all(1)
                beta = np.linalg.lstsq(A[good], y[ok].to_numpy()[good], rcond=None)[0]
                har[h][te] = np.c_[np.ones(len(te)), Hf.iloc[te].to_numpy()] @ beta
        if verbose:
            print(f"  fold {fi + 1}/{len(starts)} listo ({time.time() - t0:.0f}s)", flush=True)

    res = {"mode": mode, "n_folds": len(starts), "dir": {}, "vol": {}, "exp": {}, "bt": {}}
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
        p, y = pred[("exp", h)], T[f"exp_{h}"].to_numpy()
        m = tested & np.isfinite(p) & np.isfinite(y)
        res["exp"][h] = dict(bss=1 - brier(p[m], y[m]) / brier(base[("exp", h)][m], y[m]),
                             auc=auc(p[m], y[m]), ece=ece(p[m], y[m]))
    best_dsr, nets = None, {}
    for h in HORIZONS:
        r = T[f"ret_{h}"].to_numpy()
        m = tested & (hidx % h == 0) & np.isfinite(pred[("dir", h)]) & np.isfinite(r)
        bt, net = backtest(pd.Series(pred[("dir", h)][m], index=panel.index[m]),
                           pd.Series(r[m], index=panel.index[m]), ts[m], h)
        bt["dsr"] = deflated_sharpe(net, N_TRIALS * len(HORIZONS))
        res["bt"][h] = bt

    vs = float(np.mean([res["vol"][h]["skill_vs_har"] for h in VOL_HORIZONS]))
    eb = float(np.mean([res["exp"][h]["bss"] for h in VOL_HORIZONS]))
    db = float(np.mean([res["dir"][h]["bss"] for h in HORIZONS]))
    res["summary"] = dict(vol_skill=vs, exp_bss=eb, dir_bss=db,
                          best_net_sharpe=max(v["net_sharpe"] for v in res["bt"].values()),
                          score={"vol": vs + eb, "dir": db, "all": vs + eb + db}[METRIC],
                          seconds=time.time() - t0, n_trials=N_TRIALS)
    res["gates"] = gates(res)
    return res


def gates(res):
    g = {
        "vol_gana_a_HAR_en_>=3_de_4_horizontes": sum(res["vol"][h]["skill_vs_har"] > 0 for h in VOL_HORIZONS) >= 3,
        "expansion_vol_BSS>0_en_>=3_de_4": sum(res["exp"][h]["bss"] > 0 for h in VOL_HORIZONS) >= 3,
        "calibracion_ECE<0.03_en_exp_y_dir": all(res["exp"][h]["ece"] < 0.03 for h in VOL_HORIZONS)
                                             and all(res["dir"][h]["ece"] < 0.03 for h in HORIZONS),
        "direccion_BSS>0_en_>=3_de_5": sum(res["dir"][h]["bss"] > 0 for h in HORIZONS) >= 3,
        "backtest_neto_Sharpe>0_y_DSR>0.95_en_algun_h": any(v["net_sharpe"] > 0 and (v["dsr"] or 0) > 0.95
                                                            for v in res["bt"].values()),
    }
    return g


def report(res):
    print(f"\n=== {res['mode'].upper()} | folds={res['n_folds']} | {res['summary']['seconds']:.0f}s ===")
    print("DIRECCION      h   BSS      AUC     ECE     acc")
    for h, v in res["dir"].items():
        print(f"               {h:>2}  {v['bss']:+.4f}  {v['auc']:.4f}  {v['ece']:.4f}  {v['acc']:.4f}")
    print("VOLATILIDAD    h   R2       HAR_R2   skill_vs_HAR   | expansion: BSS    AUC    ECE")
    for h in VOL_HORIZONS:
        v, e = res["vol"][h], res["exp"][h]
        print(f"               {h:>2}  {v['r2']:.4f}  {v['har_r2']:.4f}   {v['skill_vs_har']:+.4f}       |            "
              f"{e['bss']:+.4f}  {e['auc']:.4f} {e['ece']:.4f}")
    print(f"BACKTEST L/S neto ({COST_BPS:.0f}bps/lado)  h   n     netSharpe  grossSharpe  net_bps/período  turnover  DSR")
    for h, v in res["bt"].items():
        print(f"                                   {h:>2}  {v['n']:>5}  {v['net_sharpe']:+.2f}      {v['gross_sharpe']:+.2f}"
              f"        {v['net_bps']:+.2f}          {v['turnover']:.2f}    {v['dsr']:.3f}")
    print("GATES:")
    for k, ok in res["gates"].items():
        print(f"  [{'OK' if ok else '--'}] {k}")
    print("SUMMARY_JSON:" + json.dumps(res["summary"]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if cmd == "download":
        download(int(sys.argv[2]) if len(sys.argv) > 2 else 730)
    else:
        r = evaluate(cmd)
        report(r)
        with open(f"report_{cmd}.json", "w") as f:
            json.dump(r, f, indent=1, default=str)
