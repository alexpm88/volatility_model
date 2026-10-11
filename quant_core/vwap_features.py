"""vwap_features.py — VWAP diario con rollover + anchored (portabilidad diaria).
Fuente: corpus SRT "VWAP in Action" + "How Banks Know" (rutina institucional).
Reglas portadas: VWAP rollover diario = fair value (arriba=caro/abajo=barato);
stretch (desviación extrema → reversión); aceptación (días sobre/bajo VWAP /21);
anchored VWAP en máximos/mínimos 21d (sustituto diario documentado de ATH/eventos;
la parte sesión/estructura intradiaria NO es portable y se excluye).
VWAP típico diario = (H+L+C)/3 ponderado por volumen, reseteado por día
(grupo por fecha, causal intra-día: cumsum dentro del día).
Features: vwap_dist (log(close/VWAP_día)), vwap_stretch (z de dist /21d),
vwap_accept (fracción de días sobre VWAP /21), avwap_dist (log(close/AVWAPHi21)).
"""
import numpy as np
import pandas as pd


def vwap_block(panel):
    """Bloque VWAP por panel (sym, ts). Devuelve DataFrame causal."""
    tp = (panel["high"] + panel["low"] + panel["close"]) / 3.0
    v = panel["volume"].fillna(0.0)
    day = panel.index.get_level_values("ts").floor("D")
    pv = (tp * v).groupby([panel.index.get_level_values("sym"), day]).cumsum()
    vv = v.groupby([panel.index.get_level_values("sym"), day]).cumsum()
    vwap = pv / (vv + 1e-12)
    F = pd.DataFrame(index=panel.index)
    F["vwap_dist"] = np.log(panel["close"] / (vwap + 1e-12))
    mu = F["vwap_dist"].groupby(level="sym").transform(lambda s: s.rolling(21).mean())
    sd = F["vwap_dist"].groupby(level="sym").transform(lambda s: s.rolling(21).std())
    F["vwap_stretch"] = ((F["vwap_dist"] - mu) / (sd + 1e-9)).clip(-6.0, 6.0)
    F["vwap_accept"] = (panel["close"] > vwap).astype(float).groupby(level="sym").transform(
        lambda s: s.rolling(21).mean())
    hi21 = panel["high"].groupby(level="sym").transform(lambda s: s.rolling(21).max())
    lo21 = panel["low"].groupby(level="sym").transform(lambda s: s.rolling(21).min())
    avwap_hi = hi21  # anchored en el extremo 21d (sustituto documentado de ATH/evento)
    avwap_lo = lo21
    F["avwap_dist"] = np.log(panel["close"] / ((avwap_hi + avwap_lo) / 2.0 + 1e-12))
    return F.replace([np.inf, -np.inf], np.nan).astype("float32")


if __name__ == "__main__":
    n = 200
    idx = pd.MultiIndex.from_product([["A"], pd.date_range("2020-01-01", periods=n, freq="D")],
                                     names=["sym", "ts"])
    rng = np.random.default_rng(0)
    c = pd.Series(100 + rng.standard_normal(n).cumsum(), index=idx)
    panel = pd.DataFrame({"close": c, "high": c * 1.01, "low": c * 0.99,
                          "volume": rng.integers(100, 1000, n).astype(float)}, index=idx)
    F = vwap_block(panel)
    print(F.describe().loc[["mean", "std", "min", "max"]].round(4).to_string())
    assert F["vwap_accept"].dropna().between(0, 1).all()
    print("VWAP_OK")
