---
ticket: unfiled (bug, filed at PR-open)
stack: screamingface-engine, screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-19
finished: 2026-10-19
---

# sdk-span-time-order — a backward clock step must not abort a successful run

## Intent

The SDK sometimes aborts a run that the Engine finished successfully. In 1 of 3 identical full
160-case cached replays of FrontierScience (claude-opus-5.5, local kind stack), `sf.evaluate`
raised `ValueError: Span end cannot precede start` (`events.py:304`, `_validate_span_times`,
from `Span.__post_init__`) via `_engine/contract.py` `_span` <- `run_lifecycle.py:48` <-
`_engine/transport.py:537` `_run_connected`. The Engine's run summary for that run said
`outcome=succeeded`, 300 cache hits. A bad telemetry span must not destroy a successful result.

## Root cause

- **Producer (Engine runner).** Both ends of every wire span come from the WALL clock, read at
  two moments: `_RunState.map` sets `start = datetime.now(UTC)` when it drains `NodeStarted`
  (`runner/executor.py` NodeStarted branch) and `_finish` sets `end = datetime.now(UTC)` when it
  drains `NodeFinished`. CLOCK_REALTIME is not monotonic. On the kind-on-Colima stack the guest
  clock steps BACK about 211 ms every 10 s: systemd-timesyncd slews the VM ahead (offset
  +293 ms, frequency saturated at +500 ppm) and lima-guestagent `SyncTime` steps it back to the
  host time ("drift was ~211ms"; 35,490 steps in the journal). Most spans last about 2 us (both
  events drain from the `_Bridge` in one batch), so a step between NodeStarted and NodeFinished
  gives `end < start` by up to about 211 ms. A run lasts about 5 s and a step comes every 10 s,
  so the failure is intermittent.
- **Consumer (SDK wire adapter).** `contract._span` passes the Engine's `start`/`end` straight
  into the public value type `events.Span`, whose `__post_init__` raises a bare `ValueError`
  (not even an `ExecutionError`). Nothing between `_run_connected` and the caller catches it.
  The adapter already resolves other incoherent producer telemetry with `_LOG.warning` and a
  rule (cost total vs parts); the span-time case had no such rule.

## Evidence

- `executor.py` NodeStarted: `_SpanState(event.node_kind, event.detail, datetime.now(UTC), ...)`;
  `_finish`: `end=datetime.now(UTC)`; unknown-id fallback `_SpanState("", "", datetime.now(UTC),
  None)`. The same module already uses `time.monotonic()` for run duration.
- `url4/streaming/protocol/signals.py` `SpanData.start/end`: no `end >= start` validator (the
  wire contract does not state the order).
- Timing match: the failing run's log mtime is 2026-10-19T09:11:49-0300; the VM journal has a
  guestagent step at 09:11:49 (drift 210.909 ms). The successful replay (3532 spans, 0 inverted)
  had its 09:12:39 step inside a 1.926 s gap with no events.
- Unit repros: a clock that returns T0 then T0-211ms gives an Engine `SpanData` with
  `end < start`; `contract._span` on that span raises `ValueError`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`: `_SpanState` gets
  `start_monotonic`; `_finish` sets `end = start + monotonic elapsed (>= 0)`; the unknown-id
  fallback gets `end == start`.
- `apps/screamingface-engine/src/screamingface_engine/tracing/span_tree.py`: docstring note only.
- `packages/screamingface/src/screamingface/_engine/contract.py` `_span`: an inverted span is
  clamped (`end = start`) with a `_LOG.warning`, not dropped.
- tests: `apps/screamingface-engine/tests/unit/test_span_time_order.py` (new),
  `packages/screamingface/tests/test_span_time_tolerance.py` (new).

## Test plan

- E1 a backward wall step between NodeStarted and NodeFinished: `end >= start`, and
  `end - start` is the monotonic delta (2 ms).
- E2 a NodeFinished for an unknown span id: `end == start`.
- E3 a forward wall step does not inflate the duration.
- S1 `contract._span` with end 211 ms before start: no exception, `end == start`, one WARNING
  on `screamingface._engine.contract`.
- S2 the real cache-hit stream with its hit span inverted (and no cache summary): the run
  outcome still counts the hit and its saving (clamp, not drop).
- Existing public value-type tests (`test_event_values.py`, `test_value_validation.py`) stay
  unchanged and green.

## Acceptance

- E1-E3 and S1-S2 RED before the fix, GREEN after; all gates green for both stacks.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** one `fix(screamingface-engine): ...` commit on branch `sdk-span-time-order` (local, not pushed).
- **RED -> GREEN:** before the fix E1-E3 failed (`end` 211 ms before `start`; fallback
  `end != start`; forward step gave a 5 s duration) and S1-S2 raised
  `ValueError: Span end cannot precede start`. After the fix all 5 pass.
- **Gates (final re-run before commit, both ALL GATES GREEN):** `run_gates.py screamingface-engine --base origin/main` ALL GATES GREEN (after
  `uv sync --dev`, as CI does: a stale local venv with the `inspect` extra gave 10 pyright
  errors in `tests/unit/inspect`, unrelated); `run_gates.py screamingface --base origin/main` ALL
  GATES GREEN (after `uv sync --extra notebook`, as CI does).
- **Deviations:** `_finish` reads `time.monotonic()` once at its top, so the unknown-id
  fallback span opens and closes at the same reading (`end == start` exactly). The engine
  fix reaches the live stack only after an image rebuild (not done here: the cluster is shared),
  so it is verified by unit tests only.
- **Follow-ups (not filed):** Started/Terminated envelope times (`url4/streaming/lifecycle.py`
  `time=datetime.now(UTC)`) can invert for a run shorter than one step (~211 ms), so
  `report.py` raises "completed_at cannot precede started_at"; the wall-clock OTLP spans in
  `tracing/accept.py` and `tracing/relay.py` can get negative durations in SigNoz.
