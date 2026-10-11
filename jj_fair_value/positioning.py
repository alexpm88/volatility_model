"""jj_fair_value/positioning.py — Prop-firm position & money management (JJ framework).

Pure-math, zero dependency on the volatility_model `multi/` harness.
Full mapping + formula table: docs/notes/jj_fair_value_mapping.md §2.

JJ transcripts refs: risk-of-ruin (L43:25-45:29), cost-per-funded (L24:26-24:49),
funded EV (L24:53-25:13), RR tiers (L11:01-45:01), kill-switch (L34:36-34:39),
static risk/TP-first sizing (L57:00-59:25), account stratification (L37:59, L57:12).

JJ rule: optimize TP FIRST; the stop is "essentially random" -> risk = the
account's max-loss budget, TP = required_tp_points * point_value * contracts,
RR = TP / risk. We cap RR 1:1.5 (evals) .. 1:6 (unlimited funded NQ).
"""
from __future__ import annotations
from dataclasses import dataclass

# JJ's static profit-target point buckets (discrete tiers the dashboard optimizes).
RR_TIERS = (25, 38, 50, 75, 100)


def risk_of_ruin(pass_rate: float, n_eval: int) -> float:
    """P(losing `n_eval` consecutive evals) = (1 - pass_rate)^n.

    JJ L75:04-75:11: with a 91% eval-failure rate you lose $100 x9 but the single
    payout (~$2k+) wins it back — risk-of-ruin bounds the bankroll needed.
    """
    if not 0.0 <= pass_rate <= 1.0:
        raise ValueError("pass_rate must be in [0, 1]")
    if n_eval < 0:
        raise ValueError("n_eval must be >= 0")
    return (1.0 - pass_rate) ** n_eval


def expected_cost_per_funded(eval_cost: float, pass_rate: float) -> float:
    """Average spend to secure one funded account = eval_cost / pass_rate.

    JJ L24:26-24:49: cost_per_funded = eval_cost / pass_rate; a strategy is
    profitable when EV(funded) > cost_per_funded.
    """
    if not 0.0 < pass_rate <= 1.0:
        raise ValueError("pass_rate must be in (0, 1]")
    if eval_cost < 0:
        raise ValueError("eval_cost must be >= 0")
    return eval_cost / pass_rate


def funded_expected_value(avg_payout: float, payout_prob: float) -> float:
    """Expected value of a funded account's lifetime = avg_payout * payout_prob.

    JJ L25:03-25:13: only payouts matter (max-loss is sunk eval cost).
    """
    if avg_payout < 0:
        raise ValueError("avg_payout must be >= 0")
    if not 0.0 <= payout_prob <= 1.0:
        raise ValueError("payout_prob must be in [0, 1]")
    return avg_payout * payout_prob


@dataclass(frozen=True)
class AccountPlan:
    """Static position plan for one prop-firm account (JJ: optimize TP first)."""
    rr: float
    tp_points: int
    eval_mode: bool


def rr_tier(has_consistency: bool, has_live_cap: bool, points_to_fair) -> AccountPlan:
    """Pick the static R/R + TP tier for an account from its rule class.

    JJ L11:01-45:01: consistency / live-cap accounts -> conservative 1:1.5..1:2
    (reach goal faster); unlimited accounts -> scale up to 1:3..1:6 (JJ: 1:6 max
    on ~100pt TP). `points_to_fair=None` -> default evaluation plan (38pt, 1:1.5).
    """
    if points_to_fair is None:
        return AccountPlan(rr=1.5, tp_points=38, eval_mode=True)
    tier = min(RR_TIERS, key=lambda t, p=points_to_fair: abs(t - p))
    cap = max(has_consistency, has_live_cap)
    if cap:
        rr = max(1.5, min(2.0, tier / 25.0))
    else:
        rr = max(3.0, min(6.0, tier / 25.0))
    return AccountPlan(rr=rr, tp_points=tier, eval_mode=False)


def session_kill_switch(consecutive_losses: int, max_losses: int = 3) -> bool:
    """JJ L34:36-34:39: stop trading a session after `max_losses` consecutive
    losers — the market is trending, not reverting."""
    if consecutive_losses < 0 or max_losses < 1:
        raise ValueError("losses/threshold must be positive")
    return consecutive_losses >= max_losses


def optimal_risk_static(required_tp_points: int, max_loss_dollars: float,
                        contracts: int = 1, point_value: float = 50.0) -> dict:
    """Static position plan (JJ L57:00-59:25 / 66:05-66:48).

    JJ optimizes TP FIRST and leaves the stop "essentially random": the dollar
    risk = the account's max-loss budget; TP = required_tp_points * point_value *
    contracts; RR = TP / risk. `point_value`=50 for NQ ($50/pt per contract).
    """
    if required_tp_points <= 0:
        raise ValueError("required_tp_points must be > 0")
    if max_loss_dollars <= 0:
        raise ValueError("max_loss_dollars must be > 0")
    if contracts < 1:
        raise ValueError("contracts must be >= 1")
    tp_dollars = required_tp_points * point_value * contracts
    rr = tp_dollars / max_loss_dollars
    return {"risk_dollars": max_loss_dollars, "tp_dollars": tp_dollars,
            "rr": rr, "contracts": contracts, "tp_points": required_tp_points}


def account_stratification(points_in_favor: int, tp_tiers=RR_TIERS) -> int:
    """JJ L37:59 / L57:12: route each trade to the account whose TP tier is
    nearest to `points_in_favor` (maximizes realized EV per account rule set)."""
    if points_in_favor < 0:
        raise ValueError("points_in_favor must be >= 0")
    if not tp_tiers:
        raise ValueError("tp_tiers must be non-empty")
    return min(tp_tiers, key=lambda t, p=points_in_favor: abs(t - p))
