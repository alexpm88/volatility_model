"""jj_fair_value — JJ fair-value / prop-firm position-management toolkit.

Standalone directional prop-trading package (JJ fair-value theory from the
JJ-Simon transcript). It does NOT import or mutate the volatility_model
`multi/` harness — that harness is off-limits per AGENTS.md L1, and
`dir_bss` is structurally near-random (AUC ~0.53, B1 true-OOS), so JJ's
*directional* signal cannot reuse the shipped `score=vol_skill+exp_bss`
engine. The *position-management* math below is portable and is what this
package ships as a reusable, tested module.

Modules:
  - signal:        fair-value reversion / displacement / breakout / news-drift
                   entry logic (reference signal — NQ-futures oriented).
  - positioning:   prop-firm static R/R, consistency, risk-of-ruin, expected
                   cost per funded, funded EV, session kill-switch, stratification.
  - test_positioning: unit tests (run: `python -m jj_fair_value.test_positioning`).

AUTH / OUT-OF-RIELES gate (per HANDOFF §10, TODO V5.1-A1):
  - Building this as a *separate* research package: ALLOWED (research sandbox).
  - Wiring it into the shipped volatility_model pipeline (`multi/prepare_multi.py`,
    `multi/strategy_multi.py`, `backtest_ls`): OUT-OF-RIELES — requires explicit
    auth + harness exception (harness off-limits). See docs/notes/jj_fair_value_mapping.md.
"""
from .signal import (fair_price_session_open, fair_value_bias, is_displacement,
                     is_breakup_structure, expected_news_direction, session_window)
from .positioning import (risk_of_ruin, expected_cost_per_funded, funded_expected_value,
                          rr_tier, AccountPlan, session_kill_switch,
                          optimal_risk_static, account_stratification, RR_TIERS)

__all__ = [
    "fair_price_session_open", "fair_value_bias", "is_displacement",
    "is_breakup_structure", "expected_news_direction", "session_window",
    "risk_of_ruin", "expected_cost_per_funded", "funded_expected_value",
    "rr_tier", "AccountPlan", "session_kill_switch",
    "optimal_risk_static", "account_stratification", "RR_TIERS",
]
