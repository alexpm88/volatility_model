"""
signals.py - Cálculo de señales causales, scoring cuantitativo de activos y ranking mensual.
Incorpora:
- Momentum y tendencia ajustada por riesgo
- Volatilidad realizada y Roughness Hurst (H)
- Dividend yield y persistencia de pagos
- Quality & Low Volatility Scoring
"""

import numpy as np
import pandas as pd

def compute_asset_features(panel):
    """
    Calcula features cuantitativas causales sobre el panel (symbol, date).
    """
    df = panel.copy()
    c = df["close"]
    hi = df["high"]
    lo = df["low"]
    v = df["volume"]
    div = df["dividend"]
    
    def _tr(s, fn):
        return s.groupby(level="symbol").transform(fn)
        
    # 1. Retornos y Log-retornos
    lr = np.log(c / c.groupby(level="symbol").shift(1))
    
    # 2. Volatilidad Realizada a 21d, 63d y 126d (anualizada)
    rv21 = np.sqrt(_tr(lr ** 2, lambda s: s.rolling(21).mean()) * 252)
    rv63 = np.sqrt(_tr(lr ** 2, lambda s: s.rolling(63).mean()) * 252)
    
    # 3. Parkinson Volatility (rango High-Low más eficiente)
    park = (np.log(hi / lo) ** 2) / (4 * np.log(2))
    park21 = np.sqrt(_tr(park, lambda s: s.rolling(21).mean()) * 252)
    
    # 4. Momentum a corto (21d), medio (63d) y largo plazo (126d)
    mom21 = _tr(c, lambda s: s.pct_change(21))
    mom63 = _tr(c, lambda s: s.pct_change(63))
    mom126 = _tr(c, lambda s: s.pct_change(126))
    
    # 5. Momentum ajustado por volatilidad (Sharpe Ratio rodante de señal)
    mom_sharpe63 = mom63 / (rv63 + 1e-6)
    
    # 6. Trend Strength (medias móviles EMA21 / EMA63)
    ema21 = _tr(c, lambda s: s.ewm(span=21).mean())
    ema63 = _tr(c, lambda s: s.ewm(span=63).mean())
    trend_ratio = (ema21 - ema63) / (ema63 + 1e-6)
    
    # 7. Drawdown individual desde el máximo histórico rodante (126d)
    max126 = _tr(c, lambda s: s.rolling(126).max())
    dd126 = (c - max126) / (max126 + 1e-6)
    
    # 8. Dividend Yield rodante anualizado (últimos 252 días de pagos / precio actual)
    div_sum252 = _tr(div, lambda s: s.rolling(252).sum())
    div_yield = div_sum252 / (c + 1e-6)
    
    # 9. Asignar al DataFrame
    df["lr"] = lr
    df["rv21"] = rv21
    df["rv63"] = rv63
    df["park21"] = park21
    df["mom21"] = mom21
    df["mom63"] = mom63
    df["mom126"] = mom126
    df["mom_sharpe63"] = mom_sharpe63
    df["trend_ratio"] = trend_ratio
    df["dd126"] = dd126
    df["div_yield"] = div_yield
    
    return df

def rank_and_select_top_k(df, current_date, top_k=20, min_history=126):
    """
    Dada una fecha de rebalanceo, evalúa la sección cruzada de todos los activos disponibles
    y selecciona el top_k con el mayor Composite Multi-Factor Score:
    Score = 0.40 * Rank(Mom_Sharpe) + 0.30 * Rank(-RV63 [Baja Vol]) + 0.20 * Rank(Div_Yield) + 0.10 * Rank(Trend)
    """
    # Filtrar datos hasta current_date
    sub = df.xs(current_date, level="date")
    
    # Validar que tengan datos suficientes
    valid = sub.dropna(subset=["mom_sharpe63", "rv63", "div_yield", "trend_ratio"]).copy()
    if top_k is None or len(valid) < top_k:   # P5.7: None => full-breadth (todos valid)
        # Si hay menos, tomar los que haya
        top_k = len(valid)
        
    if len(valid) == 0:
        return []
        
    # Ranks percentilares cross-seccionales (0 a 1)
    r_mom = valid["mom_sharpe63"].rank(pct=True)
    r_lowvol = (-valid["rv63"]).rank(pct=True)  # Menor volatilidad = mayor rank
    r_div = valid["div_yield"].rank(pct=True)
    r_trend = valid["trend_ratio"].rank(pct=True)
    
    composite_score = 0.35 * r_mom + 0.30 * r_lowvol + 0.20 * r_div + 0.15 * r_trend
    valid["composite_score"] = composite_score
    
    selected = valid.sort_values(by="composite_score", ascending=False).head(top_k)
    return selected.index.tolist()
