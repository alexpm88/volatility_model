"""volume_profile.py — POC / Value Area rodantes causales (aprox. diaria).
Fuente: corpus SRT "Volume Profile Guide" + "How Banks Know" (liquidez).
Definiciones: POC = precio con más volumen en la ventana; VAH/VAL = banda
mínima que acumula el 70% del volumen (value area); HVN = dentro (imán,
consolidación), LVN = fuera (movimiento rápido).
Portabilidad: sin footprint intradiario → POC aproximado por la vela con
máximo volumen de la ventana (típico diario HIPÓTESIS documentada); VAH/VAL
= percentiles 15/85 del rango ponderado por volumen en la ventana.
Todo con rolling causal (min_periods = ventana); sin futuro.
Features: poc_dist_w (log(close/POC)), in_va_w (1/0), va_width_w (ancho
relativo: compresión vs expansión del valor).
"""
import numpy as np
import pandas as pd


def _poc_va(g, w):
    """g: DataFrame de un símbolo con close/high/low/volume. Devuelve POC/VAH/VAL."""
    c, v = g["close"].to_numpy(), g["volume"].to_numpy()
    n = len(g)
    poc = np.full(n, np.nan)
    vah = np.full(n, np.nan)
    val = np.full(n, np.nan)
    for i in range(w - 1, n):
        sl = slice(i - w + 1, i + 1)
        vv = v[sl]
        if not np.isfinite(vv).any() or vv.sum() <= 0:
            continue
        j = int(np.nanargmax(vv))
        poc[i] = c[sl][j]
        cc = c[sl]
        lo, hi = np.nanpercentile(cc, [15, 85])
        val[i], vah[i] = lo, hi
    return poc, vah, val


def volume_profile_block(panel, windows=(21, 63)):
    """Bloque POC/VA por panel (sym, ts). Devuelve DataFrame causal."""
    F = pd.DataFrame(index=panel.index)
    for w in windows:
        parts = []
        for sym, g in panel.groupby(level="sym"):
            poc, vah, val = _poc_va(g, w)
            parts.append(pd.DataFrame({"poc": poc, "vah": vah, "val": val}, index=g.index))
        B = pd.concat(parts).sort_index()
        F[f"poc_dist_{w}"] = np.log(panel["close"] / B["poc"])
        F[f"in_va_{w}"] = ((panel["close"] <= B["vah"]) & (panel["close"] >= B["val"])).astype(float)
        F[f"va_width_{w}"] = (B["vah"] - B["val"]) / (panel["close"] + 1e-9)
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


if __name__ == "__main__":
    n = 300
    idx = pd.MultiIndex.from_product([["A", "B"], pd.date_range("2020-01-01", periods=n, freq="D")],
                                     names=["sym", "ts"])
    rng = np.random.default_rng(0)
    c = pd.Series(100 + rng.standard_normal(len(idx)).cumsum(), index=idx)
    panel = pd.DataFrame({"close": c, "high": c * 1.01, "low": c * 0.99,
                          "volume": rng.integers(100, 1000, len(idx)).astype(float)}, index=idx)
    F = volume_profile_block(panel)
    print(F.describe().loc[["mean", "std", "min", "max"]].round(4).to_string())
    assert F.filter(like="in_va").dropna().isin([0.0, 1.0]).all().all()
    print("VOLPROFILE_OK")
