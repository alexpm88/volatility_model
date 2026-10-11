"""Unit tests for jj_fair_value positioning + signal math (JJ framework).

Run:  python -m jj_fair_value.test_positioning
      python -m jj_fair_value.test_signal
No pytest dependency required (plain asserts + __main__ runner).
"""
from jj_fair_value.positioning import (risk_of_ruin, expected_cost_per_funded,
    funded_expected_value, rr_tier, AccountPlan, session_kill_switch,
    optimal_risk_static, account_stratification, RR_TIERS)
from jj_fair_value.signal import (fair_price_session_open, fair_value_bias,
    is_displacement, is_breakup_structure, expected_news_direction)


# ---------------- positioning ----------------
def test_risk_of_ruin():
    # JJ L75:04-75:11 example framing: pass 25% -> 3 in a row losing prob
    assert abs(risk_of_ruin(0.25, 3) - 0.421875) < 1e-9
    assert risk_of_ruin(1.0, 10) == 0.0     # never loses
    assert risk_of_ruin(0.0, 5) == 1.0      # always loses
    assert risk_of_ruin(0.5, 0) == 1.0      # n=0 -> "ruin" by definition of 0 trials
    try:
        risk_of_ruin(1.5, 1); assert False
    except ValueError:
        pass

def test_cost_per_funded():
    # JJ L24:26: $100 eval / 25% pass -> $400 / funded
    assert expected_cost_per_funded(100.0, 0.25) == 400.0
    assert expected_cost_per_funded(100.0, 1.0) == 100.0

def test_funded_ev():
    # JJ L25:03: avg $2000 payout, 75% payout prob -> $1500 EV
    assert funded_expected_value(2000.0, 0.75) == 1500.0
    assert funded_expected_value(0.0, 0.9) == 0.0

def test_rr_tier_eval_default():
    p = rr_tier(True, False, None)
    assert p.eval_mode is True
    assert p.tp_points == 38          # JJ's default eval TP (L61:32 / 2538)
    assert p.rr == 1.5                # JJ: evals always 1:1.5

def test_rr_tier_consistency_conservative():
    p = rr_tier(True, False, 100)     # consistency account, 100pts to fair
    assert p.eval_mode is False
    assert p.tp_points == 100
    assert p.rr <= 2.0                # consistency caps RR (L44:46-45:01)

def test_rr_tier_unlimited_scales():
    p = rr_tier(False, False, 100)    # no consistency, no live cap, 100pts
    assert p.rr >= 3.0                # unlimited -> scale up to 1:6 (L66:39-66:48)
    assert p.rr <= 6.0

def test_session_kill_switch():
    assert session_kill_switch(3, max_losses=3) is True
    assert session_kill_switch(2, max_losses=3) is False

def test_optimal_risk_static():
    # 38pt TP, $500 max-loss, 1 contract, NQ $50/pt -> TP=$1900, RR=3.8
    r = optimal_risk_static(38, 500.0, contracts=1, point_value=50.0)
    assert r['tp_dollars'] == 1900.0
    assert abs(r['rr'] - 3.8) < 1e-9
    assert r['contracts'] == 1

def test_account_stratification():
    assert account_stratification(40) == 38          # nearest tier
    assert account_stratification(90) == 100
    assert account_stratification(12) == 25          # 12 closer to 25 than 0

# ---------------- signal ----------------
def test_fair_price_non_news():
    assert fair_price_session_open(4500.0) == 4500.0          # open is fair
    assert fair_price_session_open(4500.0, 4490.0) == 4490.0  # news -> pre-news

def test_fair_value_bias():
    assert fair_value_bias(4510, 4500) == 1   # long > fair -> short-biased
    assert fair_value_bias(4490, 4500) == -1  # long < fair -> long-biased
    assert fair_value_bias(4500, 4500) == 0

def test_displacement():
    # short: bigger body + close below prev low
    assert is_displacement(body=30, prev_body=20, close=42, prev_low=45, prev_high=50,
                           direction="short") is True
    # long: bigger body + close above prev high
    assert is_displacement(body=30, prev_body=20, close=55, prev_low=45, prev_high=50,
                           direction="long") is True
    # smaller body -> not a displacement
    assert is_displacement(body=10, prev_body=20, close=42, prev_low=45, prev_high=50,
                           direction="short") is False

def test_breakup_structure():
    # short: wick below both neighbors + confirmed break
    assert is_breakup_structure(wick=100, prev_wick1=102, prev_wick2=103,
                                broke=True, direction="short") is True
    # not broken yet -> false
    assert is_breakup_structure(wick=100, prev_wick1=102, prev_wick2=103,
                                broke=False, direction="short") is False

def test_expected_news_direction():
    assert expected_news_direction(0.5, is_expected=True) == 0      # priced in
    assert expected_news_direction(0.5, is_expected=False) == 1    # drift up
    assert expected_news_direction(-0.3, is_expected=False) == -1

# ---------------- runner ----------------
_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in _TESTS:
        t(); print("ok  -", t.__name__)
    print("ALL %d TESTS PASSED" % len(_TESTS))
