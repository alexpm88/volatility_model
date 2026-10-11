"""kalman_features.py — Filtro de Kalman escalar para reversión a la media adaptativa.
Fuente: corpus SRT "Trading Mean Reversion with Kalman Filters" (OU + Kalman).
Modelo: nivel m_t = m_{t-1} + K_t·(x_t − m_{t-1}), K_t = P/(P+R),
P = (1−K_{t-1})·P + Q. Trade-off documentado: Q/R alto = confía en el dato
(whipsaw), bajo = confía en el modelo (lento). Q/R FIJOS (no se optimizan).
Entrada x = log-close por símbolo; todo causal (recursión hacia adelante).
Features: kalm_level (media adaptativa), kalm_gain (K actual: rég.de confianza),
kalm_z ((x−m)/sqrt(P): distancia en bandas adaptativas), kalm_slope (cambio
del nivel /21d: deriva del "true mean" — la tesis del video).
"""
import numpy as np
import pandas as pd

Q, R0 = 1e-5, 4e-4   # Q/R = 0.025: confía en el modelo (lento, anti-whipsaw)


def _kalman(x):
    x = np.asarray(x, float)
    m = np.empty_like(x)
    z = np.empty_like(x)
    k = np.empty_like(x)
    lvl, P = x[0] if np.isfinite(x[0]) else 0.0, 1.0
    for i, xi in enumerate(x):
        if not np.isfinite(xi):
            m[i], z[i], k[i] = lvl, 0.0, 0.0
            continue
        K = P / (P + R0)
        lvl = lvl + K * (xi - lvl)
        P = (1 - K) * P + Q
        m[i], z[i], k[i] = lvl, (xi - lvl) / max(np.sqrt(P), 1e-9), K
    return m, z, k


def kalman_block(close):
    """Bloque Kalman por panel (sym, ts). Devuelve DataFrame causal."""
    lc = np.log(close)
    F = pd.DataFrame(index=close.index)
    lvl = lc.groupby(level="sym").transform(lambda s: _kalman(s.to_numpy())[0])
    z = lc.groupby(level="sym").transform(lambda s: _kalman(s.to_numpy())[1])
    gn = lc.groupby(level="sym").transform(lambda s: _kalman(s.to_numpy())[2])
    F["kalm_level"] = lvl
    F["kalm_z"] = z.clip(-8.0, 8.0)
    F["kalm_gain"] = gn
    F["kalm_slope"] = lvl.groupby(level="sym").diff(21) / 21.0
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


if __name__ == "__main__":
    n = 500
    idx = pd.MultiIndex.from_product([["A"], pd.date_range("2020-01-01", periods=n, freq="D")],
                                     names=["sym", "ts"])
    rng = np.random.default_rng(0)
    ou = np.zeros(n)
    for i in range(1, n):
        ou[i] = ou[i - 1] * 0.98 + rng.standard_normal() * 0.02
    c = pd.Series(100 * np.exp(ou), index=idx)
    F = kalman_block(c)
    print(F.describe().loc[["mean", "std", "min", "max"]].round(4).to_string())
    assert np.isfinite(F["kalm_z"].dropna()).all()
    print("KALMAN_OK Q/R=%.4f" % (Q / R0))
