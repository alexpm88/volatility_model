"""directional/data.py — OHLCV data interface for the JJ directional system.

Independent of the `multi/` harness. Provides:
  - synthetic_fair_value_series: deterministic NQ-like OHLCV (price ~16000) with
    aligned 90-bar sessions. REVERT sessions (price returns to fair) drive winning
    displacements; TREND sessions (price spikes up then crashes below fair) drive
    a 3-consecutive-losing-displacement streak -> kill-switch (JJ L34:36).
  - load_ohlcv_csv: generic CSV adapter (future NQ/US-data feed).
No data is fetched from the shipped volatility_model universe (SPY/GLD/.../BTC);
this is a SEPARATE data path for the out-of-rieles directional track.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

WINDOW = 90  # JJ session length (L15:07), bars per session for the synthetic.
DROP_STEPS = (14.0, 17.0, 20.0, 23.0, 26.0)  # strictly-increasing bodies => displace


def synthetic_fair_value_series(n_bars: int = 450, fair: float = 16000.0,
                                seed: int = 42) -> pd.DataFrame:
    """Deterministic OHLCV. Each 90-bar session: bar0 open at fair, bar1 SMALL
    spike (sets bias), bar2 a LARGE displacement candle. REVERT sessions (s%3!=2)
    revert to fair -> winning entry. TREND sessions (s%3==2) crash below fair ->
    3 consecutive losing displacements -> kill-switch. Tuples are (O,H,L,C,V)."""
    rng = np.random.default_rng(seed)
    rows = []
    n_sessions = max(1, (n_bars + WINDOW - 1) // WINDOW)
    for s in range(n_sessions):
        if len(rows) >= n_bars:
            break
        up = (s % 2 == 0)                 # spike up -> SHORT bias (revert down)
        trend = (s % 3 == 2)
        # bar0: session open at fair
        rows.append((fair, fair + 1.0, fair - 1.0, fair, 1000))
        # bar1: small unfair spike (small body so bar2 beats it)
        sp = fair + (5.0 if up else -5.0)
        rows.append((fair, max(fair, sp) + 1.0, min(fair, sp) - 1.0, sp, 800))
        if trend:
            cur = sp
            for step in DROP_STEPS:
                c = cur + (-step if up else step)        # drift AWAY from fair
                rows.append((cur, max(cur, c) + 1.0, min(cur, c) - 1.0, c, 600))
                cur = c
        else:
            disp_c = fair + (-2.0 if up else 2.0)        # large reversion candle
            rows.append((sp, max(sp, disp_c) + 1.0, min(sp, disp_c) - 1.0, disp_c, 600))
        # pad the rest of the session with flat bars (body 0 => never displace)
        target = min((s + 1) * WINDOW, n_bars)
        while len(rows) < target:
            c0 = float(rows[-1][3])
            rows.append((c0, c0, c0, c0, 300))  # truly-flat quiet bar
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    return df.head(n_bars)


def load_ohlcv_csv(path: str) -> pd.DataFrame:
    """Generic OHLCV CSV adapter (timestamp,open,high,low,close,volume)."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df.reset_index(drop=True)
