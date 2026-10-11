# directional — JJ fair-value directional engine (out-of-rieles)

A **new, independent** directional system. It runs in a **separate thread**
("otro hilo") alongside the shipped `volatility_model` (V5.1+B2) and **does NOT
modify** the `multi/` harness — that harness is off-limits per `AGENTS.md`.

Authorization: out-of-rieles granted by the user (09-Oct). See
`docs/notes/jj_fair_value_mapping.md` §7 and `HANDOFF.md` §10.

## Architecture

```
data.py        OHLCV interface (synthetic session generator + CSV loader)
fair_value.py  FairValueSignal      — per-bar fair price / displacement / breakup
positioning.py PositionManager      — kill-switch (3-loss), RR tier, static risk
                (wraps jj_fair_value.positioning primitives)
pipeline.py    DirectionalPipeline  — signal -> position -> risk -> trade plan
                DirectionalRunner  — runs the pipeline in a separate thread
                (emits trades via a Queue)
test_directional.py  self-test (8 asserts, ~5s)
```

`jj_fair_value/` (signal + positioning) is **reused**, not duplicated.
`multi/` is **not imported**.

## Run

```bash
python -m directional.test_directional      # self-test
python -c "from directional import DirectionalRunner; from directional.data import synthetic_fair_value_series as g; r=DirectionalRunner(); r.start(g()); r.join(); print(r.trades()[:2])"
```

## JJ model mapping

| JJ concept            | directional/ mapping            |
|------------------------|---------------------------------|
| session open = fair    | FairValueSignal (fair_s = open) |
| displacement entry     | signal.is_displacement          |
| breakup entry          | signal.is_breakup_structure     |
| 3-loss kill-switch     | positioning.session_kill_switch |
| TP-first sizing        | positioning.optimal_risk_static |

## Status / integrity

- `diff multi/strategy_multi.py multi/snapshots/strategy_multi_best.py` => identical
  (harness untouched).
- directional/ is standalone — its `dir_bss` ceiling (~AUC 0.53 per B1 true-OOS)
  is a documented limitation, NOT a regression of V5.1+B2.
