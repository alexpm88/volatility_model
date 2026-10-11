"""stress_eval.py - Evaluacion de resistencia a crisis (V4.3) sobre el snapshot multi.
Independiente del harness prepare_multi.py (no lo edita). Carga strategy_multi.py vigente
(== snapshot) y evalúa las gates de SPECS §3 restringidas a ventanas de crisis: entrena
pre-crisis (con embargo) y predice OOS sobre el episodio. Reusa
brier/ece/auc/deflated_sharpe/backtest_ls/gates/make_targets/har_features de prepare_multi.

Ventanas: GFC-2008, deuda-soberana, COVID-2020, shocks-de-tasas-2022 (panel 1993->2026).
"""
import os, sys, json, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from prepare import brier, ece, auc, deflated_sharpe
import importlib.util as _ilu
spec = _ilu.spec_from_file_location("strategy_multi", os.path.join(HERE, "strategy_multi.py"))
S = _ilu.module_from_spec(spec); spec.loader.exec_module(S)
import prepare_multi as pm

METRIC = os.environ.get("LOOP_METRIC", "vol")
N_TRIALS = int(os.environ.get("VOL_N_TRIALS", 1))

CRISIS = {
    "GFC-2008":        ("2008-09-15", "2009-03-31"),
    "Deuda-soberana":  ("2010-05-06", "2012-09-30"),
    "COVID-2020":      ("2020-02-19", "2020-04-10"),
    "Shocks-tasas-22": ("2022-03-16", "2023-03-10"),
}
TASKS = [("dir", h) for h in pm.HORIZONS] + [("vol", h) for h in pm.VOL_HORIZONS] + [("exp", h) for h in pm.VOL_HORIZONS]


def _build_res(panel_train, panel_test, cost_map):
    Ttr = pm.make_targets(panel_train); Tte = pm.make_targets(panel_test)
    Htr = pm.har_features(panel_train); Hte = pm.har_features(panel_test)
    ftr = S.build_features(panel_train); fte = S.build_features(panel_test)
    if not fte.index.equals(panel_test.index):
        raise ValueError("build_features: indice de test != panel")
    n = len(panel_test)
    pred = {k: np.full(n, np.nan) for k in TASKS}
    base = {k: np.full(n, np.nan) for k in TASKS}
    har = {h: np.full(n, np.nan) for h in pm.VOL_HORIZONS}
    syms_te = panel_test.index.get_level_values("sym")
    costs_te = pd.Series(syms_te).map(cost_map).to_numpy()
    for (task, h) in TASKS:
        ytr = Ttr[f"{task}_{h}"]; m = ytr.notna().to_numpy()
        if int(m.sum()) < 50:
            continue
        Xtr, ytrv = ftr.loc[panel_train.index[m], :], ytr[m]
        mdl = S.fit(Xtr, ytrv, task, h)
        pred[(task, h)] = mdl.predict(fte)
        base[(task, h)] = np.full(n, float(ytrv.mean()))
        if task == "vol":
            A = np.c_[np.ones(int(m.sum())), Htr[m].to_numpy()]; good = np.isfinite(A).all(1)
            if good.sum() >= 10:
                beta = np.linalg.lstsq(A[good], ytrv.to_numpy()[good], rcond=None)[0]
                har[h] = np.c_[np.ones(n), Hte.to_numpy()] @ beta
    ts_te = panel_test.index.get_level_values("ts")
    tested = np.ones(n, bool)
    res = {"dir": {}, "vol": {}, "exp": {}, "bt": {}}
    for h in pm.HORIZONS:
        p, y, bm = pred[("dir", h)], Tte[f"dir_{h}"].to_numpy(), base[("dir", h)]
        mask = tested & np.isfinite(p) & np.isfinite(y)
        res["dir"][h] = dict(bss = 1 - brier(p[mask], y[mask]) / brier(bm[mask], y[mask]),
                              auc = auc(p[mask], y[mask]), ece = ece(p[mask], y[mask]),
                              acc = float(((p[mask] > .5) == (y[mask] > .5)).mean()))
    for h in pm.VOL_HORIZONS:
        p, y, bm = pred[("vol", h)], Tte[f"vol_{h}"].to_numpy(), base[("vol", h)]
        mask = tested & np.isfinite(p) & np.isfinite(y)
        mse_m, mse_b = np.mean((p[mask]-y[mask])**2), np.mean((bm[mask]-y[mask])**2)
        mh = har[h][mask]
        hmask = np.isfinite(mh)
        mse_h = float(np.nanmean((mh[hmask]-y[mask][hmask])**2)) if int(hmask.sum()) >= 2 else float("nan")
        res["vol"][h] = dict(r2 = 1 - mse_m / mse_b,
                               skill_vs_har = 1 - mse_m / mse_h if np.isfinite(mse_h) and mse_h > 0 else float("nan"))
        p2, y2, b2 = pred[("exp", h)], Tte[f"exp_{h}"].to_numpy(), base[("exp", h)]
        m2 = tested & np.isfinite(p2) & np.isfinite(y2)
        res["exp"][h] = dict(bss = 1 - brier(p2[m2], y2[m2]) / brier(b2[m2], y2[m2]) if m2.sum() else float("nan"),
                               auc = auc(p2[m2], y2[m2]), ece = ece(p2[m2], y2[m2]))
    for h in pm.HORIZONS:
        r, p = Tte[f"ret_{h}"].to_numpy(), pred[("dir", h)]
        m = tested & np.isfinite(p) & np.isfinite(r)
        bt, net = pm.backtest_ls(p[m], r[m], ts_te[m], syms_te[m], costs_te[m], h)
        bt["dsr"] = deflated_sharpe(net, N_TRIALS * len(pm.HORIZONS))
        res["bt"][h] = bt
    # placebo intra-fecha (6 seed) — necesario por gates() multi (placebo_best_sharpe)
    pb = 0.0; codes, uniq = pd.factorize(ts_te)
    for h in pm.HORIZONS:
        r, p = Tte[f"ret_{h}"].to_numpy(), pred[("dir", h)]
        m = tested & np.isfinite(p) & np.isfinite(r)
        pp = p[m]; cm = codes[m] if len(codes)==len(p) else codes
        for sd in range(6):
            rng = np.random.default_rng(sd); perm = pp.copy()
            for c in range(len(uniq)):
                idx = np.where(cm == c)[0]; perm[idx] = rng.permutation(perm[idx])
            btp, _ = pm.backtest_ls(perm, r[m], ts_te[m], syms_te[m], costs_te[m], h)
            pb = max(pb, btp["net_sharpe"])
    res["summary"] = dict(best_net_sharpe = max((v["net_sharpe"] for v in res["bt"].values()), default=0.0),
                            placebo_best_sharpe = float(pb))
    return res


def score_window(res):
    vs = float(np.nanmean([res["vol"][h]["skill_vs_har"] for h in pm.VOL_HORIZONS]))
    eb = float(np.nanmean([res["exp"][h]["bss"] for h in pm.VOL_HORIZONS]))
    db = float(np.nanmean([res["dir"][h]["bss"] for h in pm.HORIZONS]))
    return dict(vol_skill=vs, exp_bss=eb, dir_bss=db, best_net_sharpe=res["summary"]["best_net_sharpe"],
                score={"vol": vs + eb, "dir": db, "all": vs + eb + db}[METRIC])


def main():
    panel = pm.load_panel()
    ts = panel.index.get_level_values("ts")
    _, cost_map = pm.load_universe()
    print(f"[stress] panel rows={len(panel)} range={ts.min().date()}->{ts.max().date()} METRIC={METRIC}")
    pm.check_causal(S, panel)
    uts = np.sort(np.array(ts.unique()))
    cut = pd.Timestamp(uts[int(len(uts) * (1 - pm.VAULT_FRAC))])
    out = {}
    gated = set()
    tr0, te0 = panel[ts < cut], panel[ts >= cut]
    res0 = _build_res(tr0, te0, cost_map); s0 = score_window(res0); g0 = pm.gates(res0)
    out["baseline_vault_oos"] = dict(window=(str(cut.date()), str(ts.max().date())),
        train_rows=len(tr0), test_rows=len(te0), summary=s0, gates=g0)
    print("\n=== BASELINE (vault OOS) ===")
    print(f"  score={s0['score']:.5f} dir_bss={s0['dir_bss']:+.4f} exp_bss={s0['exp_bss']:+.4f} "
          f"vol_skill={s0['vol_skill']:+.4f} best_net_sharpe={s0['best_net_sharpe']:+.3f}")
    print("  gates:", json.dumps({k: bool(g0[k]) for k in g0}))
    for name, (a, b) in CRISIS.items():
        t0, t1 = pd.Timestamp(a), pd.Timestamp(b)
        tr = panel[ts < t0 - pd.Timedelta(days=pm.EMBARGO)]
        te = panel[(ts >= t0) & (ts <= t1)]
        res = _build_res(tr, te, cost_map); s = score_window(res); g = pm.gates(res)
        out[name] = dict(window=(a, b), train_rows=len(tr), test_rows=len(te), summary=s, gates=g)
        print(f"\n=== CRISIS {name} ({a}->{b}) | train_rows={len(tr)} test_rows={len(te)} ===")
        print(f"  score={s['score']:.5f} dir_bss={s['dir_bss']:+.4f} exp_bss={s['exp_bss']:+.4f} "
              f"vol_skill={s['vol_skill']:+.4f} best_net_sharpe={s['best_net_sharpe']:+.3f}")
        print("  gates:", json.dumps({k: bool(g[k]) for k in g}))
    with open(os.path.join(HERE, "stress_m34.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\n[stress] -> {os.path.join(HERE, 'stress_m34.json')}")
    print("[stress] Gate-5: modelo pre-crisis no debe colapsar; comparar dir_bss/exp_bss/vol_skill/gates vs baseline.")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    main()
