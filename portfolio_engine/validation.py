"""
validation.py — Batería de validación del motor de carteras (mismo espíritu que prepare.py).

 1) FOLDS SECUENCIALES: sub-períodos independientes de negociación, con las features calentadas
    sólo con el pasado (nunca con datos del propio fold) -> mide estabilidad entre regímenes.
 2) PLACEBO MULTI-SEED: sustituye la selección por K activos al AZAR en cada rebalanceo, con el
    mismo motor, costos y vol targeting. OJO: en una cartera long-only de acciones el placebo NO
    es ~0 (en un mercado alcista una selección aleatoria también sube), así que el test correcto
    es de SKILL RELATIVO: el Sharpe de la estrategia debe superar el percentil 90 del placebo.
 3) SENSIBILIDAD: rejilla top_k x target_vol x rebalance_freq (robustez a hiperparámetros).

Salida: reports/validation.json
"""

import json
import os

import numpy as np
import pandas as pd

from .backtester import PortfolioBacktester
from .optimizer import compute_inverse_vol_weights


def _stats(nav):
    """Métricas de un tramo de NAV (el tramo parte del capital disponible en su primer día)."""
    nav = nav.dropna()
    if len(nav) < 30:
        return {}
    ret = (nav / nav.shift(1) - 1.0).dropna()
    years = len(nav) / 252.0
    sd = ret.std()
    return dict(days=len(nav), total_return=float(nav.iloc[-1] / nav.iloc[0] - 1.0),
                cagr=float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else float("nan"),
                ann_vol=float(sd * np.sqrt(252)) if len(ret) > 1 else float("nan"),
                sharpe=float(ret.mean() / sd * np.sqrt(252)) if len(ret) > 1 and sd > 0 else float("nan"),
                max_drawdown=float((nav / nav.cummax() - 1.0).min()))


class _PlaceboBT(PortfolioBacktester):
    """Idéntico al backtester real, pero elige K activos AL AZAR en cada fecha de rebalanceo."""

    def __init__(self, panel, seed=0, **kw):
        self._rng = np.random.default_rng(seed)
        super().__init__(panel, **kw)

    def _target_weights(self, date):
        if self._in_bear_regime(date):
            return pd.Series(dtype=float), float("nan"), 0.0   # régimen bajista => cash
        cross = self.df.xs(date, level="date")
        names = [s for s in cross.index if np.isfinite(cross.loc[s, "rv63"])]
        if len(names) < 2:
            return pd.Series(dtype=float), float("nan"), 0.0
        pick = list(self._rng.choice(names, size=min(self.top_k, len(names)), replace=False))
        rv = cross["rv63"].reindex(pick).dropna()
        w = compute_inverse_vol_weights(rv, max_weight=self.max_stock_weight)
        hist = self.df["lr"].unstack("symbol").loc[:date].tail(self.vol_lookback).reindex(columns=list(w.index))
        cov = hist.cov().values * 252.0
        port_vol = float(np.sqrt(max(w.values @ cov @ w.values, 0.0)))
        lev = float(np.clip(self.target_vol / port_vol, 0.0, self.max_leverage)) if port_vol > 0 else 0.0
        return w * lev, port_vol, lev


def run_folds(panel, n_folds=5, **kw):
    """Folds contiguos sobre las fechas YA activas (descontado el calentamiento de features)."""
    all_dates = sorted(panel.index.get_level_values("date").unique())
    active = all_dates[kw.get("min_history", 126):]
    edges = np.linspace(0, len(active), n_folds + 1).astype(int)
    out = []
    for k in range(n_folds):
        d0, d1 = active[edges[k]], active[min(edges[k + 1], len(active) - 1)]
        sub = panel[panel.index.get_level_values("date") <= d1]      # features con pasado, nada futuro
        bt = PortfolioBacktester(sub, **kw)
        bt.run()
        s = _stats(bt.history["nav"].loc[d0:])
        if s:
            s.update(fold=k + 1, start=str(pd.Timestamp(d0).date()), end=str(pd.Timestamp(d1).date()))
        out.append(s)
    return out


def run_placebo(panel, seeds=10, **kw):
    """Distribución placebo del Sharpe con selección aleatoria (misma cartera y costos)."""
    out = []
    for sd in range(seeds):
        bt = _PlaceboBT(panel, seed=sd, **kw)
        bt.run()
        s = _stats(bt.history["nav"])
        if s:
            s.update(seed=sd)
        out.append(s)
    return out


def run_sensitivity(panel, top_ks=(10, 15, 20), vols=(0.08, 0.10, 0.12), freqs=(21, 42), **kw):
    """Robustez del Sharpe a los hiperparámetros de construcción de cartera."""
    out = []
    for tk in top_ks:
        for tv in vols:
            for rf in freqs:
                bt = PortfolioBacktester(panel, top_k=tk, target_vol=tv, rebalance_freq=rf, **kw)
                bt.run()
                s = _stats(bt.history["nav"])
                if s:
                    s.update(top_k=tk, target_vol=tv, rebalance_freq=rf)
                out.append(s)
    return out


def validate(panel=None, n_folds=5, seeds=10, out_dir=None, verbose=True, **kw):
    """Ejecuta la batería completa, evalúa los gates y guarda reports/validation.json.

    ``**kw`` se reenvía a cada ``PortfolioBacktester`` (p.ej. ``commission_bps``,
    ``slippage_bps``, ``top_k``, ``target_vol``), preservando la causalidad de los
    folds (features calientan sólo con pasado). Costos por defecto = 5 bps/lado
    (backward compatible: validar() sin kwargs reproduce idéntico a antes)."""
    if panel is None:
        from .data_loader import load_or_fetch_universe
        panel = load_or_fetch_universe()["panel"]

    print("[Validation] 1/3 backtest base...")
    base = PortfolioBacktester(panel, **kw)
    base.run()
    m = base.metrics()

    print("[Validation] 2/3 folds secuenciales...")
    folds = [f for f in run_folds(panel, n_folds=n_folds, **kw) if f]
    print("[Validation] 3/3 placebo multi-seed + sensibilidad...")
    plac = [p for p in run_placebo(panel, seeds=seeds, **kw) if p]
    sens = [s for s in run_sensitivity(panel, **kw) if s]

    ps = np.array([p["sharpe"] for p in plac])
    ks = np.array([s["sharpe"] for s in sens])
    fs = np.array([f["sharpe"] for f in folds])
    dd = np.array([f["max_drawdown"] for f in folds])
    gates = {
        "folds_con_Sharpe>0_en_>=80%": float(np.mean(fs > 0)) >= 0.80,
        "estrategia_supera_percentil90_del_placebo": bool(m["sharpe"] > np.percentile(ps, 90)),
        "sensibilidad_Sharpe>0_en_>=90%_de_la_rejilla": float(np.mean(ks > 0)) >= 0.90,
        "ningun_fold_con_drawdown_peor_que_-25%": bool(np.all(dd > -0.25)),
    }
    res = dict(base=m, folds=folds, placebo=plac, sensitivity=sens, gates=gates,
               summary=dict(placebo_sharpe_mean=float(ps.mean()), placebo_sharpe_p90=float(np.percentile(ps, 90)),
                            placebo_sharpe_max=float(ps.max()), sens_sharpe_mean=float(ks.mean()),
                            sens_sharpe_min=float(ks.min()), folds_sharpe_mean=float(fs.mean()),
                            folds_sharpe_min=float(fs.min()), n_backtests=1 + len(folds) + len(plac) + len(sens)))
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "validation.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    if verbose:
        report(res)
    return res


def report(res):
    """Imprime el resumen de la batería de validación."""
    s, m = res["summary"], res["base"]
    print("\n=== VALIDACION MOTOR DE CARTERAS ===")
    print(f"base           sharpe {m['sharpe']:+.2f}  CAGR {m['cagr']:+.2%}  MDD {m['max_drawdown']:.2%}")
    print(f"folds ({len(res['folds'])})       sharpe medio {s['folds_sharpe_mean']:+.2f}  peor {s['folds_sharpe_min']:+.2f}")
    for f in res["folds"]:
        print(f"   fold {f['fold']} {f['start']}->{f['end']}  sharpe {f['sharpe']:+.2f}  ret {f['total_return']:+.2%}  MDD {f['max_drawdown']:.2%}")
    print(f"placebo ({len(res['placebo'])})  sharpe medio {s['placebo_sharpe_mean']:+.2f}  p90 {s['placebo_sharpe_p90']:+.2f}  max {s['placebo_sharpe_max']:+.2f}")
    print(f"sensibilidad    sharpe medio {s['sens_sharpe_mean']:+.2f}  peor {s['sens_sharpe_min']:+.2f}  ({len(res['sensitivity'])} combinaciones)")
    print(f"GATES ({sum(res['gates'].values())}/{len(res['gates'])})")
    for k, v in res["gates"].items():
        print(f"  [{'OK' if v else '--'}] {k}")
    return res


if __name__ == "__main__":
    validate()

