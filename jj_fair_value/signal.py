"""jj_fair_value/signal.py — JJ fair-value directional entry signal (NQ futures).

Pure reference logic from JJ's "fair pricing theory" (transcript ~16:00-22:00,
32:42-33:06, 54:00-59:55, 12:27-15:54). NO dependency on the volatility_model
multi/ harness and NO market-data fetch — these are pure signal predicates so
they can be unit-tested, then wired (post-auth) to a live NQ feed.

Core claims (JJ):
  * Session open (9:30 ET) is "fair" ~95% of NON-NEWS days (L82:45, 41:04-41:20).
  * On NEWS days the PRE-NEWS price is fair (8:30 red-folder is priced in) (L54:19, 12:55-13:41).
    UNEXPECTED news (tweets/speeches) REPRICES fair value (L14:21-14:50).
  * Entry toward fair value: DISPLACEMENT candle (body > prev body AND close beyond
    prev wick) or BREAKUP structure (wick beyond two adjacent candles + break) (L55:23-56:55).
  * 90-minute session windows: NY AM, London, NY PM (L15:07-15:50).

OUT-OF-RIELES gate: this is a DIRECTIONAL signal. The volatility_model's
`dir_bss` is structurally near-random (B1 true-OOS AUC ~0.53, gate FAIL), so
this signal is NOT bolted onto `multi/strategy_multi.py` (harness off-limits +
futile). It is the standalone directional track documented in
docs/notes/jj_fair_value_mapping.md.
"""
from __future__ import annotations
from datetime import timedelta
import numpy as np


def fair_price_session_open(open_price: float, pre_news_price=None) -> float:
    """Fair price for reversion bias.

    Non-news day -> session open (JJ L348 L82:45-83:03).
    News-relevant day -> pre-news price (JJ L54:19 L61:58-62:42: pre-news
    price is fair because the news is already priced in).
    """
    return float(pre_news_price if pre_news_price is not None else open_price)


def fair_value_bias(last_price: float, fair_price: float) -> int:
    """Directional bias toward fair value: +1 = short-biased (last>fair),
    -1 = long-biased, 0 = at fair. JJ L477-478: revert to fair."""
    return int(np.sign(last_price - fair_price))


def is_displacement(body: float, prev_body: float, close: float,
                    prev_low: float, prev_high: float, direction: str = "short") -> bool:
    """Displacement candle (JJ L55:23-56:21 / 63:31-64:40).

    Two conditions (either color):
      - body > prev body (momentum/imbalance), AND
      - close beyond the previous candle's wick
        (short: close < prev_low; long: close > prev_high).
    A displacement must also 'displace a candle of the OPPOSITE color'
    (JJ L69:31-69:40) — caller guarantees color via `direction`.
    """
    if direction not in ("short", "long"):
        raise ValueError("direction must be 'short' or 'long'")
    if body <= prev_body:
        return False
    if direction == "short":
        return close < prev_low
    return close > prev_high


def is_breakup_structure(wick: float, prev_wick1: float, prev_wick2: float,
                         broke: bool = False, direction: str = "short") -> bool:
    """Breakup structure (JJ L66:19-67:05 / 54:40-55:01).

    A wick beyond the TWO adjacent candles, confirmed by a structural break.
    `broke` = a subsequent candle closed past the structure (JJ L55:54 'breaks
    the structure'). `direction` selects the valid side ('short' => wick below
    both neighbors; 'long' => wick above both).
    """
    if direction == "short":
        beyond = wick < min(prev_wick1, prev_wick2)
    else:
        beyond = wick > max(prev_wick1, prev_wick2)
    return bool(beyond and broke)


def expected_news_direction(outcome_surprise: float, is_expected: bool) -> int:
    """JJ L14:21-15:12: EXPECTED news is priced-in -> drift ~0 (revert to pre-news).
    UNEXPECTED news renews the fair price and produces a slight drift in the
    surprise direction (+1 up, -1 down). `outcome_surprise` is signed (forecast delta).
    """
    if is_expected:
        return 0
    return int(np.sign(outcome_surprise))


def session_window(ts, opens: dict, window_minutes: int = 90) -> dict:
    """JJ L15:07-15:50: only trade the first `window_minutes` (90) after each
    session open. `opens` maps session name -> open timestamp."""
    return {name: abs((ts - o).total_seconds()) <= window_minutes * 60
            for name, o in opens.items()}


def news_is_expected(red_folder_schedule: list, ts) -> bool:
    """JJ L12:55-13:01 / 12:27-12:52: 8:30 ET red-folder (CPI/PPI) is EXPECTED
    (forecasted, priced in). Tweets/speeches at other times are UNEXPECTED.
    `red_folder_schedule` = list of expected-news timestamps."""
    tol = timedelta(minutes=2)
    return any(abs(ts - t) <= tol for t in red_folder_schedule)
