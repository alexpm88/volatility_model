"""
p58_holdout.py - P5.8: Holdout 3-fold OOS validation of full-breadth (top_key=None@40syms).

Confirma que Sharpe 1.3435/4/4 (P5.6/P5.7, in-sample) no es overfit
tecnico usando datos extendidos (10y) con split walk-forward OOS.
"""

import json
import os
import time
import warnings

import numpy as np
import pandas as pd

from .data_loader import load_or_fetch_universe, DEFAULT_UNIVERSE_40
from .backtester import PortfolioBacktester
from .validation import _PlaceboBT, _stats

warnings.filterwarnings("ignore")

TOP_KEY = None
PLACEBO_TOP_K = 20
TARGET_VOL = 0.10
REBALANCE_FREQ = 21
COMMISSION_BPS = 5.0
N_FOLDS = 3
OOS_DAYS = 630
TRAIN_DAYS = 1261
MIN_HISTORY = 126
PLACEBO_SEEDS = 10
INSAMPLE_5Y_SHARPE = 1.3435

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "p58_holdout")
os.makedirs(REPORTS_DIR, exist_ok=True)



def _load_extended_panel():
    print("[P5.8] Cargando universo de 40 syms (rango 10y)...")
    try:
        pkg = load_or_fetch_universe(symbols=DEFAULT_UNIVERSE_40, range_str="10y")
    except Exception as e:
        print(f"[P5.8] Fallo fetch 10y ({e}), usando 5y cache...")
        pkg = load_or_fetch_universe()
    panel = pkg["panel"]
    all_dates = sorted(panel.index.get_level_values("date").unique())
    print(f"[P5.8] Panel: {len(pkg['symbols'])} syms, {len(all_dates)} fechas "
          f"({pd.Timestamp(all_dates[0]).date()} -> {pd.Timestamp(all_dates[-1]).date()})")
    return panel, all_dates, pkg


def _oos_backtest(panel, oos_start_date, oos_end_date, **kw):
    sub = panel[panel.index.get_level_values("date") <= oos_end_date]
    bt = PortfolioBacktester(sub, **kw)
    bt.run()
    nav = bt.history["nav"]
    oos_nav = nav.loc[oos_start_date:oos_end_date]
    s = _stats(oos_nav)
    if s:
        s.update(oos_start=str(pd.Timestamp(oos_start_date).date()),
                 oos_end=str(pd.Timestamp(oos_end_date).date()))
    return s, bt


def _oos_placebo(panel, oos_start_date, oos_end_date, seeds=PLACEBO_SEEDS, **kw):
    pb_kw = dict(kw)
    pb_kw["top_k"] = PLACEBO_TOP_K
    sub = panel[panel.index.get_level_values("date") <= oos_end_date]
    out = []
    for sd in range(seeds):
        bt = _PlaceboBT(sub, seed=sd, **pb_kw)
        bt.run()
        nav = bt.history["nav"]
        oos_nav = nav.loc[oos_start_date:oos_end_date]
        s = _stats(oos_nav)
        if s:
            s.update(seed=sd)
        out.append(s)
    return [p for p in out if p]



def run_holdout_oos():
    t0 = time.time()
    panel, all_dates, pkg = _load_extended_panel()

    needed = TRAIN_DAYS + OOS_DAYS * N_FOLDS
    if len(all_dates) < needed:
        print(f"[P5.8] ADVERTENCIA: datos insuficientes. "
              f"Necesarios {needed}, disponibles {len(all_dates)}.")
        fold_oos = len(all_dates) // (N_FOLDS + 1)
        fold_train = len(all_dates) - fold_oos * N_FOLDS
        print(f"[P5.8] Ajustando: train={fold_train}, oos={fold_oos}")
    else:
        fold_oos = OOS_DAYS
        fold_train = TRAIN_DAYS

    base_kw = dict(top_k=TOP_KEY, target_vol=TARGET_VOL, rebalance_freq=REBALANCE_FREQ,
                   commission_bps=COMMISSION_BPS, regime_filter=False, min_history=MIN_HISTORY)

    print("\n[P5.8] 1) In-sample full-breadth (10y completo)...")
    insample_bt = PortfolioBacktester(panel, **base_kw)
    insample_bt.run()
    insample = insample_bt.metrics()
    print(f"  Sharpe: {insample['sharpe']:.4f}  CAGR: {insample['cagr']:.2%}  MDD: {insample['max_drawdown']:.2%}")

    insample_placebo = _oos_placebo(panel, all_dates[0], all_dates[-1],
                                    seeds=PLACEBO_SEEDS, **base_kw)
    ps = np.array([p["sharpe"] for p in insample_placebo])
    insample_p90 = float(np.percentile(ps, 90))
    print(f"  Placebo p90 (top_k=20 random): {insample_p90:.4f}")

    print(f"\n[P5.8] 2) 3-fold walk-forward OOS (train={fold_train}, oos={fold_oos})...")
    fold_results = []
    for fold in range(N_FOLDS):
        train_end_idx = fold_train + fold * fold_oos - 1
        oos_start_idx = train_end_idx + 1
        oos_end_idx = oos_start_idx + fold_oos - 1
        if oos_end_idx >= len(all_dates):
            oos_end_idx = len(all_dates) - 1
        if oos_start_idx >= len(all_dates):
            break

        train_end_date = all_dates[train_end_idx]
        oos_start_date = all_dates[oos_start_idx]
        oos_end_date = all_dates[oos_end_idx]
        n_oos = oos_end_idx - oos_start_idx + 1

        print(f"  Fold {fold+1}/{N_FOLDS}: train hasta "
              f"{pd.Timestamp(train_end_date).date()}, "
              f"OOS {pd.Timestamp(oos_start_date).date()} -> "
              f"{pd.Timestamp(oos_end_date).date()} ({n_oos} dias)...")

        s, bt = _oos_backtest(panel, oos_start_date, oos_end_date, **base_kw)
        pb = _oos_placebo(panel, oos_start_date, oos_end_date,
                          seeds=PLACEBO_SEEDS, **base_kw)
        pb_ps = float(np.percentile([p["sharpe"] for p in pb], 90))

        if s:
            s.update(fold=fold+1, placebo_p90=pb_ps,
                     train_end=str(pd.Timestamp(train_end_date).date()))
            fold_results.append(s)
            g1 = s["sharpe"] > 0
            g2 = s["sharpe"] > pb_ps
            g3 = s["max_drawdown"] > -0.25
            gates_str = "/".join(["OK" if v else "--" for v in [g1, g2, g3]])
            print(f"    Sharpe: {s['sharpe']:.4f}  CAGR: {s['cagr']:.2%}  "
                  f"MDD: {s['max_drawdown']:.2%}  placebo_p90: {pb_ps:.4f}  "
                  f"gates: {gates_str}")

    t_elapsed = time.time() - t0
    oos_sharpes = [f["sharpe"] for f in fold_results]
    oos_mdds = [f["max_drawdown"] for f in fold_results]
    avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else float("nan")
    min_oos_sharpe = float(np.min(oos_sharpes)) if oos_sharpes else float("nan")
    worst_mdd = float(min(oos_mdds)) if oos_mdds else float("nan")

    gates = {
        "oos_sharpe_promedio_positivo": bool(avg_oos_sharpe > 0),
        "todos_los_folds_sharpe_positivo": bool(all(s > 0 for s in oos_sharpes)) if oos_sharpes else False,
        "ningun_fold_mdd_peor_que_-25pct": bool(all(m > -0.25 for m in oos_mdds)) if oos_mdds else False,
        "oos_supera_placebo_p90_en_todos_los_folds": bool(all(f["sharpe"] > f["placebo_p90"] for f in fold_results)) if fold_results else False,
        "oos_min_sharpe_supera_90pct_insample_5y": bool(min_oos_sharpe >= 0.9 * INSAMPLE_5Y_SHARPE) if oos_sharpes else False,
    }

    n_pass = sum(gates.values())
    n_total = len(gates)
    print(f"\n[P5.8] 3) Resumen:")
    print(f"  In-sample Sharpe (10y): {insample['sharpe']:.4f}")
    print(f"  P5.6/P5.7 Sharpe (5y): {INSAMPLE_5Y_SHARPE}")
    print(f"  OOS Sharpe promedio: {avg_oos_sharpe:.4f}  (min: {min_oos_sharpe:.4f})")
    print(f"  OOS MDD peor: {worst_mdd:.2%}")
    print(f"  Gates OOS: {n_pass}/{n_total}")
    for k, v in gates.items():
        print(f"    [{'OK' if v else '--'}] {k}")

    overfit = not gates["oos_min_sharpe_supera_90pct_insample_5y"] or not gates["todos_los_folds_sharpe_positivo"]
    decision = "CONFIRMED_NOT_OVERFIT" if not overfit else "SUSPECT_OVERFIT"

    summary = {
        "task": "P5.8 Full-breadth (top_key=None@40syms) holdout 3-fold OOS",
        "config": {
            "top_k": "None (full-breadth)",
            "placebo_top_k": PLACEBO_TOP_K,
            "target_vol": TARGET_VOL, "rebalance_freq": REBALANCE_FREQ,
            "commission_bps": COMMISSION_BPS, "regime_filter": False,
            "n_folds": N_FOLDS, "train_days": fold_train, "oos_days": fold_oos,
        },
        "data": {
            "symbols": len(pkg["symbols"]),
            "date_range": f"{pkg['start']} -> {pkg['end']}",
            "n_dates": len(all_dates),
        },
        "in_sample_10y": {
            "sharpe": insample["sharpe"], "cagr": insample["cagr"],
            "mdd": insample["max_drawdown"], "placebo_p90": insample_p90,
        },
        "p56_p57_ref": {"sharpe_5y": INSAMPLE_5Y_SHARPE, "source": "P5.6/P5.7 validate() 5y cache"},
        "o_os_folds": [
            {k: v for k, v in f.items() if isinstance(v, (int, float, str, bool, np.floating, np.integer))}
            for f in fold_results
        ],
        "o_os_summary": {"avg_sharpe": avg_oos_sharpe, "min_sharpe": min_oos_sharpe, "max_mdd": worst_mdd},
        "gates": gates, "gates_pass": f"{n_pass}/{n_total}",
        "decision": decision, "t_sec": round(t_elapsed, 1),
    }

    with open(os.path.join(REPORTS_DIR, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=str)

    decision_report = {
        "decision": decision,
        "insample_5y_sharpe": INSAMPLE_5Y_SHARPE,
        "insample_10y_sharpe": insample["sharpe"],
        "oos_avg_sharpe": avg_oos_sharpe,
        "oos_min_sharpe": min_oos_sharpe,
        "gates_pass": f"{n_pass}/{n_total}",
        "gates": gates,
        "note": (
            f"Holdout 3-fold OOS. In-sample 10y Sharpe {insample['sharpe']:.4f}; "
            f"OOS-avg {avg_oos_sharpe:.4f} (min {min_oos_sharpe:.4f}). "
            f"Ref P5.6/P5.7: {INSAMPLE_5Y_SHARPE} (5y). "
            + ("NO overfit: OOS consistente con in-sample 5y. Full-breadth shippable."
               if not overfit else "OVERFIT SUSPECTO: OOS degradado vs in-sample 5y.")
        ),
        "candidate_default": ("top_key=None (full-breadth) opt-in P5.7b validado OOS"
                              if not overfit else "top_key=20 INTACTO (floor conservador)"),
        "t_sec": round(t_elapsed, 1),
    }
    with open(os.path.join(REPORTS_DIR, "decision.json"), "w") as fh:
        json.dump(decision_report, fh, indent=1, default=str)

    print(f"\n[P5.8] Reportes guardados en {REPORTS_DIR}/")
    print(f"[P5.8] Decision: {decision}")
    print(f"[P5.8] Tiempo total: {t_elapsed:.1f}s")
    return summary


if __name__ == "__main__":
    results = run_holdout_oos()
