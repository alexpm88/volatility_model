"""directional — JJ fair-value directional system (out-of-rieles, independent hilo).

A NEW, INDEPENDENT system that runs in a separate thread alongside the shipped
volatility_model (V5.1+B2), WITHOUT modifying it. Reuses `jj_fair_value/`
(signal + positioning). Does NOT import or call `multi/` (harness off-limits).

Components:
  - data.synthetic_fair_value_series: deterministic NQ-like OHLCV (~16000) with
    alternating REVERT / TREND sessions so displacement signals fire and the
    kill-switch is exercised end-to-end (JJ L34:36).
  - fair_value.FairValueSignal: per-bar fair-value / displacement / breakup
    signal (session-open = fair; session bias = -sign(first spike)).
  - positioning.PositionManager: stateful prop-firm layer (kill-switch, RR tier,
    static risk) wrapping jj_fair_value.positioning.
  - pipeline.DirectionalPipeline + DirectionalRunner: signal -> position ->
    risk -> trade plan, runnable in a SEPARATE THREAD (emits trades via Queue).

AUTH: out-of-rieles granted by user (09-Oct). multi/ harness untouched.
See docs/notes/jj_fair_value_mapping.md §7.
"""
from .data import synthetic_fair_value_series, load_ohlcv_csv
from .fair_value import FairValueSignal, tp_for_points_to_fair
from .positioning import PositionManager
from .pipeline import DirectionalPipeline, DirectionalRunner

__all__ = ["synthetic_fair_value_series", "load_ohlcv_csv", "FairValueSignal",
           "tp_for_points_to_fair", "PositionManager", "DirectionalPipeline",
           "DirectionalRunner"]
