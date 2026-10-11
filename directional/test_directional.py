"""Self-test for the directional engine (out-of-rieles hilo).

Proves end-to-end (no `multi/` import): signal fires displacement, PositionManager
produces trade plans, the pipeline runs in a SEPARATE THREAD, and the kill-switch
(3 losses) engages within a crash session.
Run:  python -m directional.test_directional
"""
from __future__ import annotations
import threading
import time
from directional.data import synthetic_fair_value_series
from directional.pipeline import DirectionalRunner, DirectionalPipeline
from directional.positioning import PositionManager
from directional.fair_value import FairValueSignal


def _synthetic():
    return synthetic_fair_value_series(n_bars=450, fair=16000.0, seed=42)


def test_signal_fires_displacement():
    bars = _synthetic()
    sig = FairValueSignal(window=90).compute(bars)
    assert sig["displacement"].sum() >= 1, "displacement signal never fired"


def test_kill_switch_unit():
    pm = PositionManager(loss_cap=3)
    for _ in range(2):
        pm.on_loss()
        assert not pm.killed()
    pm.on_loss()
    assert pm.killed(), "kill-switch must fire on 3rd consecutive loss"


def test_threaded_pipeline_end_to_end():
    bars = _synthetic()
    runner = DirectionalRunner(window=90, max_loss=500.0, point_value=50.0)
    t0 = time.time()
    th = runner.start(bars)
    assert isinstance(th, threading.Thread) and th.is_alive() is not None
    runner.join(timeout=30)
    elapsed = time.time() - t0
    assert elapsed < 30.0, "thread did not finish in time"
    trades = runner.trades()
    assert isinstance(trades, list) and len(trades) >= 1, "pipeline produced no trades"
    outcomes = [x["outcome"] for x in trades]
    assert "win" in outcomes and "loss" in outcomes, "need both win+loss outcomes"
    assert any(x["kill_triggered"] for x in trades) or max(x["consecutive_losses"] for x in trades) <= 3
    # kill-switch must have tripped on the crash session
    assert max(x["consecutive_losses"] for x in trades) == 3
    for x in trades:
        assert x["rr"] > 0 and x["tp_points"] > 0


def test_pipeline_sequential_matches_thread():
    bars = _synthetic()
    seq = DirectionalPipeline().run(bars)
    th_runner = DirectionalRunner()
    th_runner.start(bars); th_runner.join(timeout=30)
    threaded = th_runner.trades()
    assert len(seq) == len(threaded), "threaded and sequential divergence"


_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for t in _TESTS:
        t(); print("ok  -", t.__name__)
    print("ALL %d DIRECTIONAL TESTS PASSED" % len(_TESTS))
