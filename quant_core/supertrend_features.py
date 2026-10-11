"""supertrend_features.py — SuperTrend con parámetros FIJOS (anti-sobreajuste).
Fuente: corpus SRT "SuperTrend en el oro 35%→75%".
RESTRICCIÓN DOCUMENTADA: el video optimiza por scan de miles de combinaciones;
hacerlo en el loop sería sobreajuste (frente C2.x saturado). Se fijan ATR=10 y
mult=3 (estándar) y sólo se expone la GEOMETRÍA (dirección/distancia/flips),
nunca el barrido de parámetros.
SuperTrend: banda sup = HL2 + mult·ATR; banda inf = HL2 − mult·ATR; dirección
persiste (guardarraíl) salvo cierre que la cruza. Todo causal (ATR Wilder con
ewm, bandas con ffill acotado por precio — sin futuro).
Features: st_dir (+1/-1), st_dist (log(close/banda activa)), st_flips_21
(cambios de dirección /21d: régimen chop vs tendencial).
"""
import numpy as np
import pandas as pd

ATR_W, MULT = 10, 3.0


def _supertrend(g):
    h, l, c = (g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy())
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.concatenate([[np.nan], c[:-1]])),
                                      np.abs(l - np.concatenate([[np.nan], c[:-1]]))))
    atr = pd.Series(tr).ewm(alpha=1.0 / ATR_W, min_periods=ATR_W, adjust=False).mean().to_numpy()
    hl2 = (h + l) / 2.0
    up, dn = hl2 - MULT * atr, hl2 + MULT * atr
    d = np.zeros(len(g))
    dirc = 1.0
    for i in range(len(g)):
        if not np.isfinite(c[i]) or not np.isfinite(atr[i]):
            d[i] = dirc
            continue
        if c[i] > dn[i - 1] if i > 0 and np.isfinite(dn[i - 1]) else False:
            dirc = 1.0
        elif c[i] < up[i - 1] if i > 0 and np.isfinite(up[i - 1]) else False:
            dirc = -1.0
        d[i] = dirc
    band = np.where(d > 0, up, dn)
    return d, np.log(c / (band + 1e-12)), pd.Series(d).diff().abs().rolling(21).sum().to_numpy()


def supertrend_block(panel):
    """Bloque SuperTrend por panel (sym, ts). Devuelve DataFrame causal."""
    F = pd.DataFrame(index=panel.index)
    parts = []
    for sym, g in panel.groupby(level="sym"):
        d, dist, flips = _supertrend(g)
        parts.append(pd.DataFrame({"st_dir": d, "st_dist": dist, "st_flips_21": flips},
                                  index=g.index))
    B = pd.concat(parts).sort_index()
    F["st_dir"] = B["st_dir"]
    F["st_dist"] = B["st_dist"]
    F["st_flips_21"] = B["st_flips_21"]
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


if __name__ == "__main__":
    n = 300
    idx = pd.MultiIndex.from_product([["A"], pd.date_range("2020-01-01", periods=n, freq="D")],
                                     names=["sym", "ts"])
    rng = np.random.default_rng(0)
    c = pd.Series(100 + rng.standard_normal(n).cumsum(), index=idx)
    panel = pd.DataFrame({"close": c, "high": c * 1.01, "low": c * 0.99,
                          "volume": np.ones(n)}, index=idx)
    F = supertrend_block(panel)
    print(F.describe().loc[["mean", "std", "min", "max"]].round(4).to_string())
    assert F["st_dir"].dropna().isin([1.0, -1.0]).all()
    print("SUPERTREND_OK ATR=%d MULT=%.1f" % (ATR_W, MULT))
