"""directional/fair_value.py — JJ fair-value signal (per bar).

Composes jj_fair_value.signal into a per-bar fair-value / displacement /
breakup signal. Session open = fair; session bias = -sign(first spike);
displacement/breakup checked in the session-bias direction (JJ: "follow a
bias"). Independent of `multi/`.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from jj_fair_value.signal import (fair_value_bias, is_displacement,
                                  is_breakup_structure)
from jj_fair_value.positioning import RR_TIERS


def tp_for_points_to_fair(points_to_fair: float) -> int:
    """Pick the nearest JJ TP tier to `points_to_fair`."""
    return int(min(RR_TIERS, key=lambda t, p=points_to_fair: abs(t - p)))


class FairValueSignal:
    """Per-bar fair-value signal over fixed-length JJ sessions (default 90)."""

    def __init__(self, window: int = 90):
        self.window = window

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        n = len(bars)
        fair = np.full(n, np.nan)
        sbias = np.zeros(n, dtype=int)            # session-level bias per bar
        for i in range(0, n, self.window):
            fair[i] = float(bars["open"].iloc[i])  # session open = fair (L82:45)
            b = 0
            if i + 1 < n:
                spike = float(bars["close"].iloc[i + 1]) - float(bars["open"].iloc[i])
                if spike != 0.0:
                    b = -int(np.sign(spike))       # spike up -> short bias (revert)
            sbias[i:i + self.window] = b
        fair_s = pd.Series(fair, index=range(n)).ffill().to_numpy()
        bias = np.zeros(n, dtype=int)
        disp = np.zeros(n, dtype=bool)
        brk = np.zeros(n, dtype=bool)
        tp = np.zeros(n, dtype=int)
        for i in range(1, n):
            f = fair_s[i]
            if np.isnan(f) or sbias[i] == 0:
                continue
            o, h, l, c = (bars[k].iloc[i] for k in ("open", "high", "low", "close"))
            pl = float(bars["low"].iloc[i - 1]); ph = float(bars["high"].iloc[i - 1])
            body = abs(c - o)
            pbody = abs(float(bars["close"].iloc[i - 1]) - float(bars["open"].iloc[i - 1]))
            d = "short" if sbias[i] == -1 else "long"
            disp[i] = is_displacement(body, pbody, c, pl, ph, direction=d)
            if i >= 2:
                w0 = l if d == "short" else h
                pc1 = float(bars["close"].iloc[i - 1]); po1 = float(bars["open"].iloc[i - 1])
                w1 = float(bars["low"].iloc[i - 1]) if pc1 < po1 else float(bars["high"].iloc[i - 1])
                pc2 = float(bars["close"].iloc[i - 2]); po2 = float(bars["open"].iloc[i - 2])
                w2 = float(bars["low"].iloc[i - 2]) if pc2 < po2 else float(bars["high"].iloc[i - 2])
                brk[i] = is_breakup_structure(w0, w1, w2, broke=True, direction=d)
            bias[i] = sbias[i]
            tp[i] = tp_for_points_to_fair(abs(c - f))
        out = bars[["open", "high", "low", "close", "volume"]].copy()
        out["fair"] = fair_s
        out["bias"] = bias
        out["displacement"] = disp
        out["breakup"] = brk
        out["tp_points"] = tp
        return out
