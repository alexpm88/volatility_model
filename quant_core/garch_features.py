"""garch_features.py — Features GARCH(1,1) causales (Engle 1982 / Bollerslev 1986).
Fuente: corpus SRT "Master Volatility with ARCH & GARCH Models".
Modelo: σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}, con α+β<1 (persistencia) y
half-life = ln(0.5)/ln(α+β). Parámetros FIJOS documentados (no se optimizan
en el loop: el frente de hiperparámetros saturado lo prohíbe).
Todo con pandas causal (shift/rolling/ewm adjust=False); sin futuro.
Features: garch_var (varianza condicional), garch_persist, garch_halflife,
garch_news (shock: r²/σ²), garch_gap (log RV21 − log σ_garch: desacuerdo
realizado vs condicional — la novedad informativa vs RV/HAR ya presentes).
"""
import numpy as np
import pandas as pd

ALPHA, BETA, OMEGA = 0.08, 0.89, 1e-7   # persistencia 0.97, half-life ~23d


def _garch_var(r):
    """Varianza condicional GARCH(1,1) por símbolo, recursión causal pura en numpy.
    Semilla v0 = media incondicional de los PRIMEROS 63 retornos (convención de
    inicialización; el transitorio decae con half-life ~23d). Como P y Pc del
    test de truncado comparten el inicio, v0 es idéntico y el estado recursivo
    coincide exactamente pasado el warmup (NaN en las primeras 63 barras)."""
    WARMUP = 63
    r = np.nan_to_num(np.asarray(r, float), nan=0.0)
    v = np.empty_like(r)
    v0 = max(float(np.nanmean(r[:WARMUP] ** 2)), 1e-8)
    s = v0
    for i, ri in enumerate(r):
        s = OMEGA + ALPHA * ri ** 2 + BETA * s
        v[i] = s
    v[:WARMUP] = np.nan
    idx = r.index if hasattr(r, "index") else None
    return pd.Series(v, index=idx)


def garch_block(close):
    """Bloque GARCH por panel (sym, ts). Devuelve DataFrame causal."""
    lr = np.log(close).groupby(level="sym").diff()
    var = lr.groupby(level="sym").transform(
        lambda s: _garch_var(s).to_numpy())
    var = var.clip(lower=1e-12)
    F = pd.DataFrame(index=close.index)
    F["garch_var"] = np.log(var + 1e-12)
    F["garch_persist"] = ALPHA + BETA
    F["garch_halflife"] = np.log(0.5) / np.log(ALPHA + BETA)
    F["garch_news"] = (lr ** 2 / var).clip(upper=25.0)
    rv21 = np.log(np.sqrt(lr.groupby(level="sym").transform(
        lambda s: s.rolling(21).mean() ** 0 if False else s.pow(2).rolling(21).mean())) + 1e-6)
    F["garch_gap"] = rv21 - 0.5 * np.log(var + 1e-12)
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


if __name__ == "__main__":
    n = 500
    idx = pd.MultiIndex.from_product([["A", "B"], pd.date_range("2020-01-01", periods=n, freq="D")],
                                     names=["sym", "ts"])
    c = pd.Series(100 * np.exp(np.random.default_rng(0).standard_normal(len(idx)).cumsum() * 0.01),
                  index=idx)
    F = garch_block(c)
    print(F.describe().loc[["mean", "std", "min", "max"]].round(4).to_string())
    assert (F["garch_halflife"] > 0).all() and np.isfinite(F["garch_var"].dropna()).all()
    print("GARCH_OK persist=%.3f halflife=%.1f" % (ALPHA + BETA, np.log(0.5) / np.log(ALPHA + BETA)))
