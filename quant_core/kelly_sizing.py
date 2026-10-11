"""kelly_sizing.py — Fracción de Kelly con estimación rodante (UTILIDAD, fuera del loop).
Fuente: corpus SRT "How to Trade with the Kelly Criterion".
Advertencia del video implementada: el Kelly con cantidades estimadas colapsa
(71%→41% prob. de acabar arriba) ⇒ half-Kelly + cap + ventana rodante + floor
de muestra mínima. Función PURA (no toca prepare*/loop*/backtests del arnés;
el backtest del arnés es de señales, no de sizing — Trial 22 dixit).
f* = (p·b − q) / b, con p = win-rate rodante, b = avg_win/avg_loss.
Uso: kelly_fraction(trade_pnl_serie, cap=0.25, half=True) → fracción en [0, cap].
"""
import numpy as np
import pandas as pd


def kelly_fraction(pnl, window=252, cap=0.25, half=True, min_trades=30):
    """Fracción de Kelly rodante causal sobre una serie de P&L por trade."""
    pnl = pd.Series(np.asarray(pnl, float))
    f = pd.Series(np.zeros(len(pnl)), index=pnl.index)
    for i in range(len(pnl)):
        w = pnl.iloc[max(0, i - window + 1):i + 1].dropna()
        if len(w) < min_trades:
            continue
        wins, losses = w[w > 0], w[w < 0]
        if len(wins) == 0 or len(losses) == 0:
            continue
        p, b = len(wins) / len(w), wins.mean() / abs(losses.mean())
        if b <= 0:
            continue
        edge = (p * b - (1 - p)) / b
        if half:
            edge *= 0.5
        f.iloc[i] = float(np.clip(edge, 0.0, cap))
    return f


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    pnl = pd.Series(np.where(rng.random(500) < 0.55, 1.5, -1.0))
    f = kelly_fraction(pnl)
    print("kelly media=%.3f max=%.3f (teórico full=%.3f)" % (f.mean(), f.max(), (0.55 * 1.5 - 0.45) / 1.5))
    assert (f >= 0).all() and (f <= 0.25 + 1e-12).all()
    print("KELLY_OK")
