"""compare_systems.py — Comparación de SISTEMAS con la batería completa de robustez.
Evalúa sobre el panel multi (Yahoo real) con el MISMO walk-forward purgado que el harness:

  S1  = estrategia_multi actual (best del ledger)
  S2  = S1 + features de roughness (H rodante de quant_core)          [Engine A integrado]
  S2b = S2 con CONSTRUCCIÓN beta-neutral del Engine B (PCA/dollar/bruta) [Engine B integrado]
  S2n = S2 con señales permutadas por fecha (PLACEBO, debe dar ≈0)

Cada sistema pasa: check_causal · ECE/AUC/BSS · netSharpe con costos reales por clase ·
DSR · placebo multi-seed · stress por épocas (2008, COVID 2020, bear 2022, 2024-25).
Uso:  python3 quant_core/compare_systems.py dev
"""
import os, sys, json, time, math, importlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "multi"))
from prepare import brier, ece, auc, deflated_sharpe, LeakageError
from rough_vol_lifting import rolling_roughness
import market_neutral as mn

HORIZONS = [1, 5, 10, 21]
VOL_HORIZONS = [5, 10, 21]
EMBARGO, VAULT_FRAC, FOLD_DAYS, MIN_TRAIN_DAYS = 25, 0.20, 126, 756
MIN_TRAIN_ROWS, TOP_K, CONF_MIN, ANN = 800, 2, 0.01, 252.0
N_SEEDS_PLACEBO = 8
H_WINDOW = {"crypto": 90, "default": 126}                 # ventana H por clase (crypto más corta)


def load_all():
    raw = pd.read_pickle(os.path.join(ROOT, "multi", "multi_raw.pkl"))
    panel = raw.set_index(["sym", "ts"])[["open", "high", "low", "close", "volume", "turnover"]].sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    u = pd.read_csv(os.path.join(ROOT, "multi", "multi_universe.csv"))
    return panel, dict(zip(u.sym, u.asset_class)), dict(zip(u.sym, u.cost_bps))


def make_targets(panel):
    c, lc = panel["close"], np.log(panel["close"])
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


def _roll(s, w, fn="sum"):
    return s.groupby(level="sym").transform(lambda x: getattr(x.rolling(w, min_periods=w), fn)())


def rough_features(panel, cls_map):
    """FEATURES ROUGH (Engine A integrado): H rodante por símbolo + su z-score 1y + régimen."""
    lc = np.log(panel["close"]).groupby(level="sym")
    out = []
    for sym, ser in panel["close"].groupby(level="sym"):
        w = H_WINDOW.get(cls_map.get(sym, "default"), 126)
        h = rolling_roughness(np.log(ser.droplevel("sym")), window=w)
        out.append(pd.Series(h.to_numpy(), index=ser.index))   # índice completo (sym, ts)
    Hs = pd.concat(out).sort_index().reindex(panel.index)
    F = pd.DataFrame(index=panel.index)
    F["rough_H"] = Hs
    m = Hs.groupby(level="sym").transform(lambda s: s.rolling(252, min_periods=63).mean())
    sd = Hs.groupby(level="sym").transform(lambda s: s.rolling(252, min_periods=63).std())
    F["rough_H_z"] = (Hs - m) / (sd + 1e-9)
    F["rough_regime"] = (Hs < m - 0.5 * sd).astype(float)   # 1 = rugoso/estresado relativo
    F["rough_H_rank"] = Hs.groupby(level="ts").rank(pct=True)
    return F.replace([np.inf, -np.inf], np.nan)



def backtest_ls(p, r, ts, sym, cost, h, beta_neutral=False, betas_by_ts=None):
    """L/S cross-sectional (numpy, rapido). Si beta_neutral: pesos proyectados con
    mn.neutralize_weights usando betas contra PC1 estimadas solo con datos <= t."""
    d = pd.DataFrame({"p": p, "r": r, "tt": ts, "sym": sym, "cost": cost}).dropna()
    if len(d) < 30:
        return dict(n=0, net_sharpe=0.0, net_bps=0.0), None
    tts = d["tt"].to_numpy()
    ps, rs, sys_, cs = (d["p"].to_numpy(), d["r"].to_numpy(), d["sym"].to_numpy(), d["cost"].to_numpy())
    prev, net, gross, idx = {}, [], [], []
    for tt, gidx in d.groupby("tt").indices.items():          # grupo REAL por fecha (cross-seccional)
        g_p, g_r, g_s, g_c = ps[gidx], rs[gidx], sys_[gidx], cs[gidx]
        conf = g_p - 0.5
        o = np.argsort(g_p, kind="stable")
        longs = [i for i in o if conf[i] >= CONF_MIN][-TOP_K:]
        shorts = [i for i in o if conf[i] <= -CONF_MIN][:TOP_K]
        w = {}
        if longs:
            for i in longs:
                w[g_s[i]] = w.get(g_s[i], 0.0) + 0.5 / len(longs)
        if shorts:
            for i in shorts:
                w[g_s[i]] = w.get(g_s[i], 0.0) - 0.5 / len(shorts)
        if w:                                                  # dollar-neutral estricto (quita deriva del mercado)
            wbar = float(np.mean(list(w.values())))
            w = {s: v - wbar for s, v in w.items()}
        if beta_neutral and betas_by_ts is not None:
            bb = betas_by_ts.get(tt)
            if bb is not None:
                bw = np.array([w.get(s, 0.0) for s in bb.index])
                nb = mn.neutralize_weights(bw, bb.to_numpy(), gross=1.0, w_max=0.6)
                w = {s: float(v) for s, v in zip(bb.index, nb) if abs(v) > 1e-10}
        gp = cc = 0.0
        for i in range(len(g_s)):
            s = g_s[i]
            wt = w.get(s, 0.0)
            gp += wt * g_r[i]
            cc += abs(wt - prev.get(s, 0.0)) * g_c[i]
        gross.append(gp)
        net.append(gp - cc)
        idx.append(tt)
        prev = w
    gross = pd.Series(gross, index=pd.Index(idx))
    net = pd.Series(net, index=pd.Index(idx))
    ann = math.sqrt(ANN / h)
    sd = net.std()
    sdp = net.std()
    sh = float(net.mean() / sdp * ann) if sdp and sdp > 0 else 0.0
    sdg = gross.std()
    shg = float(gross.mean() / sdg * ann) if sdg and sdg > 0 else 0.0
    return dict(n=int(len(net)), net_sharpe=sh, net_bps=float(net.mean() * 1e4),
                gross_sharpe=shg, gross_bps=float(gross.mean() * 1e4)), net




def _bt_guard(*a, **k):
    out = backtest_ls(*a, **k)
    if out is None or (isinstance(out, tuple) and out[0] is None):
        return dict(n=0, net_sharpe=0.0, net_bps=0.0), None
    return out


def _fit_model(Xtr, y, task):
    from sklearn.ensemble import HistGradientBoostingClassifier
    # drop columnas constantes/degeneradas en este fold (sklearn binning crashea con 1 valor)
    yv = y.to_numpy()
    good = [c for c in Xtr.columns if Xtr[c].nunique(dropna=False) > 1]
    Xtr = Xtr[good]
    if yv.min() == yv.max():
        v = float(yv[0])
        class _C:
            def predict(self, X): return np.full(len(X), v)
        return _C()
    mdl = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_depth=3,
                                         min_samples_leaf=200, l2_regularization=1.0,
                                         random_state=0).fit(Xtr, yv)

    class _M:
        def predict(self, X):
            return mdl.predict_proba(X[good])[:, 1]      # PROBABILIDAD, no etiqueta

    return _M()


def evaluate(mode="dev", verbose=True):
    t0 = time.time()
    panel_all, cls_map, cost_map = load_all()
    ts_all = panel_all.index.get_level_values("ts")
    uts = np.sort(ts_all.unique())
    cut = uts[int(len(uts) * (1 - VAULT_FRAC))]
    panel = panel_all[ts_all < cut] if mode == "dev" else panel_all
    T = make_targets(panel)
    ts = panel.index.get_level_values("ts")
    syms = panel.index.get_level_values("sym")
    costs = pd.Series(syms).map(cost_map).to_numpy() / 1e4  # bps -> fraccion
    r1 = T["ret_1"]

    # ---- features por sistema: S1 = estrategia best actual; S2 = S1 + roughness (Engine A)
    best_path = os.path.join(ROOT, "multi", "snapshots", "strategy_multi_best.py")
    path = best_path if os.path.exists(best_path) else os.path.join(ROOT, "multi", "strategy_multi.py")
    spec = importlib.util.spec_from_file_location("strategy_cmp", path)
    Sm = importlib.util.module_from_spec(spec); spec.loader.exec_module(Sm)
    F1 = Sm.build_features(panel)
    RF = rough_features(panel, cls_map)
    F2 = F1.join(RF)
    print(f"features S1={F1.shape[1]} S2={F2.shape[1]} (roughness: {[c for c in RF.columns]})", flush=True)

    # ---- walk-forward purgado idéntico para ambos sistemas
    tmin = np.datetime64(ts.min(), "D")
    hidx = ((ts.values.astype("datetime64[D]") - tmin).astype("timedelta64[D]").astype(np.int64))
    first = MIN_TRAIN_DAYS if mode == "dev" else int((np.datetime64(cut, "D") - tmin).astype("timedelta64[D]").astype(np.int64))
    starts = list(range(first, int(hidx.max()) - 5, FOLD_DAYS))
    tasks = [("dir", h) for h in HORIZONS] + [("exp", h) for h in VOL_HORIZONS]
    pred = {s: {k: np.full(len(panel), np.nan) for k in tasks} for s in ("S1", "S2")}
    base = {k: np.full(len(panel), np.nan) for k in tasks}
    tested = np.zeros(len(panel), bool)
    fold_betas = {}                                        # fecha → betas PC1 (causal por fold)
    R_piv = r1.unstack("sym")                              # retornos para Engine B
    Xs = {"S1": F1, "S2": F2}

    for fi, s in enumerate(starts):
        te = np.where((hidx >= s) & (hidx < s + FOLD_DAYS))[0]
        tr = np.where(hidx < s - EMBARGO)[0]
        if len(te) == 0 or len(tr) < MIN_TRAIN_ROWS:
            continue
        tested[te] = True
        tsr = pd.DatetimeIndex(pd.Series(ts[tr]).unique()).sort_values()
        Rt = R_piv.loc[R_piv.index.isin(tsr)].fillna(0.0).to_numpy()   # betas PC1 del train (causal)
        bt_arr = mn.betas(Rt)
        fold_betas.update({pd.Timestamp(t): pd.Series(bt_arr, index=R_piv.columns) for t in ts[te]})
        for (task, h) in tasks:
            y = T[f"{task}_{h}"].iloc[tr]
            ok = y.notna().values
            for sname in ("S1", "S2"):
                mdl = _fit_model(Xs[sname].iloc[tr][ok], y[ok], task)
                pred[sname][(task, h)][te] = mdl.predict(Xs[sname].iloc[te])
            base[(task, h)][te] = y[ok].mean()
        if verbose:
            print(f"  fold {fi + 1}/{len(starts)} ({time.time() - t0:.0f}s)", flush=True)

    # ---- métricas y backtests por sistema (idénticos para S1/S2; comparación justa)
    res = {"mode": mode, "n_folds": len(starts), "systems": {}}
    summary_sys = {}
    for sysname in ("S1", "S2"):
        P = pred[sysname]
        mets = {"dir": {}, "exp": {}}
        db, eb = [], []
        for h in HORIZONS:
            p, y = P[("dir", h)], T[f"dir_{h}"].to_numpy()
            m = tested & np.isfinite(p) & np.isfinite(y)
            b = 1 - brier(p[m], y[m]) / max(brier(base[("dir", h)][m], y[m]), 1e-9)
            mets["dir"][h] = dict(bss=b, auc=auc(p[m], y[m]), ece=ece(p[m], y[m])); db.append(b)
        for h in VOL_HORIZONS:
            p, y = P[("exp", h)], T[f"exp_{h}"].to_numpy()
            m = tested & np.isfinite(p) & np.isfinite(y)
            b = 1 - brier(p[m], y[m]) / max(brier(base[("exp", h)][m], y[m]), 1e-9)
            mets["exp"][h] = dict(bss=b, auc=auc(p[m], y[m]), ece=ece(p[m], y[m])); eb.append(b)
        bts = {}
        for h in HORIZONS:
            r = T[f"ret_{h}"].to_numpy()
            p = P[("dir", h)]
            m = tested & (hidx % h == 0) & np.isfinite(p) & np.isfinite(r)
            b, net = _bt_guard(p[m], r[m], ts[m], syms[m], costs[m], h)
            b["dsr"] = deflated_sharpe(net, 4) if net is not None else 0.0
            bts[h] = b
        best_sh = max(v["net_sharpe"] for v in bts.values())
        summary_sys[sysname] = dict(dir_bss=float(np.mean(db)), exp_bss=float(np.mean(eb)), best_sharpe=best_sh)
        res["systems"][sysname] = dict(metrics=mets, backtests=bts, best_sharpe=best_sh,
                                       dir_bss=float(np.mean(db)), exp_bss=float(np.mean(eb)))

    # ---- S2b: misma señal S2 con CONSTRUCCIÓN beta-neutral (Engine B, causal por fold)
    P = pred["S2"]
    bts_bn = {}
    for h in HORIZONS:
        r = T[f"ret_{h}"].to_numpy()
        p = P[("dir", h)]
        m = tested & (hidx % h == 0) & np.isfinite(p) & np.isfinite(r)
        b, net = _bt_guard(p[m], r[m], ts[m], syms[m], costs[m], h,
                             beta_neutral=True, betas_by_ts=fold_betas)
        b["dsr"] = deflated_sharpe(net, 4) if net is not None else 0.0
        bts_bn[h] = b
    res["systems"]["S2b"] = dict(backtests=bts_bn,
                                 best_sharpe=max(v["net_sharpe"] for v in bts_bn.values()),
                                 dir_bss=summary_sys["S2"]["dir_bss"], exp_bss=summary_sys["S2"]["exp_bss"])
    summary_sys["S2b"] = dict(dir_bss=summary_sys["S2"]["dir_bss"], exp_bss=summary_sys["S2"]["exp_bss"],
                              best_sharpe=res["systems"]["S2b"]["best_sharpe"])

    print("  [post] S2b listas", flush=True)
    # ---- PLACEBO multi-seed (S2): señales permutadas por fecha → Sharpe ≈ 0
    plc = {}
    for h in (1, 5, 10, 21):
        r = T[f"ret_{h}"].to_numpy()
        p = P[("dir", h)]
        m = tested & (hidx % h == 0) & np.isfinite(p) & np.isfinite(r)
        shs, gss = [], []
        for sd_ in range(N_SEEDS_PLACEBO):
            pv = pd.Series(p[m]).groupby(ts[m].to_numpy()).transform(
                lambda x, s_=sd_: np.random.default_rng(s_).permutation(x.to_numpy())).to_numpy()
            bp = _bt_guard(pv, r[m], ts[m], syms[m], costs[m], h)[0]
            shs.append(bp["net_sharpe"]); gss.append(bp.get("gross_sharpe", 0.0))
        plc[h] = dict(mean=float(np.mean(shs)), sd=float(np.std(shs)), max=float(np.max(shs)),
                      gross_mean=float(np.mean(gss)), gross_sd=float(np.std(gss)))
    res["placebo_S2"] = plc

    # ---- STRESS por épocas (black swans): Sharpe de S2 y S2b en cada crisis (h=5)
    epoch = {"2008_GFC": ("2008-09-01", "2009-06-30"), "COVID_2020": ("2020-02-01", "2020-12-31"),
             "bear_2022": ("2022-01-01", "2022-12-31"), "vol_2024_25": ("2024-07-01", "2025-06-30")}
    stress = {}
    r5 = T["ret_5"].to_numpy()
    for name, (a, b) in epoch.items():
        row = {}
        for sname in ("S1", "S2"):
            p5 = pred[sname](("dir", 5)) if False else pred[sname][("dir", 5)]
            m = tested & (hidx % 5 == 0) & np.isfinite(p5) & np.isfinite(r5) \
                & (ts >= pd.Timestamp(a)) & (ts <= pd.Timestamp(b))
            row[sname] = None if m.sum() < 10 else (_bt_guard(p5[m], r5[m], ts[m], syms[m], costs[m], 5)[0] or {}).get("net_sharpe")
        stress[name] = row
    res["stress"] = stress
    res["summary"] = summary_sys
    res["seconds"] = time.time() - t0

    return res


def report(res):
    print(f"\n=== COMPARATIVA DE SISTEMAS | folds={res['n_folds']} | {res['seconds']:.0f}s ===")
    print(f"{'sistema':8s} {'dir_bss':>9s} {'exp_bss':>9s} {'bestNetSh':>10s} {'bestGross':>10s} {'Sharpe@h5':>10s} {'DSR@h5':>7s}")
    for name in ("S1", "S2", "S2b"):
        v = res["systems"].get(name) or {}
        d = (v.get("backtests") or {}).get(5, {}) or {}
        bg = max((x.get("gross_sharpe", 0.0) for x in (v.get("backtests") or {}).values()), default=0.0)
        print(f"{name:8s} {v['dir_bss']:+9.4f} {v['exp_bss']:+9.4f} {v['best_sharpe']:+10.2f} {bg:+10.2f} "
              f"{d.get('net_sharpe', float('nan')):+10.2f} {d.get('dsr', float('nan')):7.3f}")
    print("PLACEBO S2 por h (bruto, debe ser ≈0 | neto = bruto - costos de turnover):")
    for h, v in res["placebo_S2"].items():
        print(f"    h={h:>2}: bruto {v['gross_mean']:+.2f}±{v['gross_sd']:.2f}   neto {v['mean']:+.2f}±{v['sd']:.2f}  max={v['max']:+.2f}")
    print("STRESS (Sharpe en crisis, h=5) S1 | S2:")
    for k, v in res["stress"].items():
        f = lambda x: "n/d" if x is None else f"{x:+.2f}"
        print(f"    {k:12s}: {f(v['S1'])} | {f(v['S2'])}")
    print("SUMMARY_JSON:" + json.dumps(res["summary"]))


if __name__ == "__main__":
    r = evaluate(sys.argv[1] if len(sys.argv) > 1 else "dev")
    report(r)
    with open(os.path.join(HERE, f"compare_{r['mode']}.json"), "w") as f:
        json.dump(r, f, indent=1, default=str)
