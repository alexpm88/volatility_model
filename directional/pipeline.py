"""directional/pipeline.py — JJ fair-value pipeline + threaded runner.

DirectionalPipeline: signal -> PositionManager -> risk -> trade plan, with a
3-loss kill-switch per session (JJ L34:36).
DirectionalRunner: runs the pipeline in a SEPARATE THREAD ("otro hilo"),
independent of the volatility_model; collects trades via a Queue.

The directional track is standalone: its dir_bss ceiling (~AUC 0.53, B1 true-OOS)
is documented in HANDOFF §10. A FAIL here does NOT regress V5.1+B2.
"""
from __future__ import annotations
import threading
import queue
import pandas as pd
from .fair_value import FairValueSignal
from .positioning import PositionManager


class DirectionalPipeline:
    """Session-level fair-value reversion pipeline over a bar stream."""

    def __init__(self, window: int = 90, max_loss: float = 500.0,
                 point_value: float = 50.0):
        self.signal = FairValueSignal(window)
        self.pos = PositionManager(max_loss, point_value)

    def reset(self) -> None:
        self.pos.reset_session()

    def run(self, bars: pd.DataFrame, emitter=None) -> list:
        """Walk-forward session-level: emit a trade dict whenever a displacement/
        breakup fires; win/loss judged by reversion toward fair; kill-switch
        stops the whole pipeline after 3 consecutive session losses."""
        sig = self.signal.compute(bars)
        trades = []
        prev_close = None
        w = self.signal.window
        n = len(sig)
        for i in range(n):
            if i % w == 0:
                self.pos.reset_session()
                prev_close = None
            if self.pos.killed():
                break
            row = sig.iloc[i]
            if not (bool(row["displacement"]) or bool(row["breakup"])):
                continue
            plan = self.pos.plan(int(row["tp_points"]))
            cur_close = float(row["close"]); f = float(row["fair"])
            prev_dist = abs(prev_close - f) if prev_close is not None else float("inf")
            outcome = "win" if abs(cur_close - f) < prev_dist else "loss"
            if outcome == "loss":
                self.pos.on_loss()
            else:
                self.pos.on_win()
            trade = {"i": i, "tp_points": plan["tp_points"], "rr": plan["rr"],
                     "fair": f, "close": cur_close, "outcome": outcome,
                     "consecutive_losses": self.pos.consecutive_losses,
                     "kill_triggered": self.pos.killed()}
            trades.append(trade)
            if emitter is not None:
                emitter.put(trade)
            prev_close = cur_close
        return trades


class DirectionalRunner:
    """Run DirectionalPipeline in a separate thread; trades via a Queue."""

    def __init__(self, window: int = 90, max_loss: float = 500.0,
                 point_value: float = 50.0):
        self.pipeline = DirectionalPipeline(window, max_loss, point_value)
        self._thread = None
        self.queue: "queue.Queue" = queue.Queue()

    def start(self, bars: pd.DataFrame) -> threading.Thread:
        self._thread = threading.Thread(target=self._target, args=(bars,), daemon=True)
        self._thread.start()
        return self._thread

    def _target(self, bars: pd.DataFrame) -> None:
        self.pipeline.reset()
        self.pipeline.run(bars, emitter=self.queue)
        self.queue.put(None)  # sentinel => "done"

    def join(self, timeout: float = 30.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def trades(self) -> list:
        out = []
        while True:
            item = self.queue.get()
            if item is None:
                break
            out.append(item)
        return out
