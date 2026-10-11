"""directional/positioning.py — JJ prop-firm PositionManager (stateful).

Wraps jj_fair_value.positioning into a stateful per-account manager: kill-switch,
RR tier, static risk. Independent of `multi/`.
"""
from __future__ import annotations
from jj_fair_value.positioning import (rr_tier, optimal_risk_static,
                                       session_kill_switch, account_stratification)


class PositionManager:
    """Stateful prop-firm position manager over a session (JJ L34:36 kill-switch)."""

    def __init__(self, max_loss_dollars: float = 500.0, point_value: float = 50.0,
                 loss_cap: int = 3, contracts: int = 1):
        self.max_loss_dollars = max_loss_dollars
        self.point_value = point_value
        self.loss_cap = loss_cap
        self.contracts = contracts
        self.consecutive_losses = 0

    def reset_session(self) -> None:
        """JJ: 3-loss rule is per-session (start fresh each 90-min window)."""
        self.consecutive_losses = 0

    def killed(self) -> bool:
        """True if the kill-switch fires (3 consecutive losses)."""
        return session_kill_switch(self.consecutive_losses, self.loss_cap)

    def on_loss(self) -> None:
        self.consecutive_losses += 1

    def on_win(self) -> None:
        self.consecutive_losses = 0

    def plan(self, points_to_fair: int, has_consistency: bool = False,
             has_live_cap: bool = False) -> dict:
        """Static position plan: optimize TP first (JJ L57:00). risk = max-loss
        budget; TP = tier * point_value * contracts."""
        ap = rr_tier(has_consistency, has_live_cap, points_to_fair)
        tier = account_stratification(points_to_fair)
        risk = optimal_risk_static(tier, self.max_loss_dollars, self.contracts,
                                   self.point_value)
        return {"rr": ap.rr, "tp_points": tier, "eval_mode": ap.eval_mode,
                "risk_dollars": risk["risk_dollars"], "tp_dollars": risk["tp_dollars"],
                "rr_realized": risk["rr"], "contracts": self.contracts}
