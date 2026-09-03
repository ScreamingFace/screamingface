# OME-906 — Bound the event bridge by memory, not by event count

- **Linear:** https://linear.app/openmined/issue/OME-906
- **Landing:** `apps/screamingface-engine`
- **Status:** implemented — stacked on PR #667, awaiting review
- **Supersedes:** `docs/spec/2026-08-20-OME-906-pipelined-frame-publishing.md`, whose premise
  was disproven by measurement. That work shipped on its own merits; it does not fix this.

## 1. The measured problem

`_Bridge.on_event` raises `BridgeOverflowError` when the buffer holds 8192 events. The
message says "the consumer is not keeping up". **Both the bound and the message describe
something that is not happening.**

### 1.1 The consumer is never behind

A trace of every produce and consume operation on one run shows 2408 operations in **16**
alternations: the producer emits hundreds of events with no interruption, then the consumer
drains all of them with no interruption.

```text
PCPCPPPPPPPPPPPP…(606 P)…PPCCCCCCCCCC…(606 C)…CCCPCPC
```

`_Bridge.drain` does not await while its buffer holds anything, and the publish path does
not suspend either. Therefore the consumer empties the buffer completely every time the
event loop schedules it. It is not slow. **It cannot run at all while the producer holds
the loop.**

### 1.2 The publisher is irrelevant

Peak backlog against publish latency, 1500 nodes:

| Publish delay | serial: time / peak | pipelined: time / peak |
|---|---|---|
| 0 ms | 0.64 s / 4497 | 0.59 s / 4461 |
| 0.1 ms | 3.80 s / 4499 | 0.58 s / 4467 |
| 1 ms | 3.83 s / 4499 | 0.59 s / 4458 |
| 10 ms | 31.05 s / 4499 | 0.59 s / 4461 |

The delay moves over a 100x range. The peak does not move.

### 1.3 What the cap really bounds

The cap bounds **how many events the engine emits between two chances for the drain to
run**. Two lines set the burst size:

- `packages/url4/src/url4/dag/executor.py:182` — `_eval` emits `NodeStarted` **before** it
  awaits anything.
- `packages/url4/src/url4/dag/executor.py:186` — it then fans out over `node.deps` with a
  plain `asyncio.gather`, with no bound.

So a DAG of width W puts about W `NodeStarted` events in the buffer in ONE event-loop slice.
Measured burst against run size:

| N | total events | largest burst |
|---|---|---|
| 300 | 1204 | 606 |
| 600 | 2404 | 1491 |
| 1200 | 4804 | 3555 |
| 2400 | 9604 | 7179 |

7179 against 8192 predicts the measured boundary exactly: 2000 nodes pass, 3000 raise.

`DEFAULT_RUN_CONCURRENCY` (32) does not bound this. Its docstring and
`packages/url4/src/url4/dag/executor.py:391` are explicit — it gates `ctx.io.fetch` through
a `BoundedIOLayer`, not node resolution.

**The 8192 cap is a ceiling on DAG width.** A 100-Case DRACO Fusion is legitimately about
3500 nodes wide, so it sits at the limit. Cache hits add the rest: they let many calls
finish in one coalesced burst, so the trailing `Usage` + `ModelResponse` + `NodeFinished`
triples also arrive in one slice. That is why the issue's snapshot shows 3465 `NodeStarted`
for only 561 calls.

### 1.4 The quantity being protected

Measured: `NodeStarted` is 278 B, `NodeFinished` is 232 B. So 8192 events is **2.1 MB**.

The same process accepts a result of `DEFAULT_RESULT_HARD_CAP_BYTES`, which is **1 GiB**. It
refuses 2.1 MB of telemetry.

## 2. Constraints

| ID | Constraint | Reason |
|---|---|---|
| C1 | A legitimately wide DAG must complete | This is the defect |
| C2 | Memory must stay bounded | The bound's real purpose |
| C3 | A genuinely stuck consumer must still fail the run | Do not trade one silent failure for another |
| C4 | No span, cost, result or terminal event is lost | Only a `Log` is safe to discard |
| C5 | The error message must describe what happened | The current one misdirects |

## 3. Design

Two changes, both in `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`.

### 3.1 Bound the buffer by a memory budget

Replace the count-derived hard cap with a cap derived from a stated memory budget:

```python
BRIDGE_MEMORY_BUDGET_BYTES = 64 * 1024 * 1024
EVENT_SIZE_ESTIMATE_BYTES = 512
```

`hard_cap = BRIDGE_MEMORY_BUDGET_BYTES // EVENT_SIZE_ESTIMATE_BYTES`, about 131 000 events.

WHY an estimate and not real measurement: `sys.getsizeof` per event on the hot path costs
more than the bound is worth, and the estimate only has to be the right order of magnitude
to turn a 2 MB ceiling into a 64 MB one. 512 B is deliberately about double the measured
278 B, so the real ceiling is under budget rather than over it.

WHY 64 MB: it is 30x the widest burst measured here and still small beside the 1 GiB this
process already accepts for a result. The run mode is a one-shot Job, so the budget is spent
once and reclaimed on exit.

The budget must be settable from `job_env`, like the result caps, so an operator can lower
it for a memory-tight pod without a release.

### 3.2 Say what actually happened

The current message blames the consumer. Replace it with the real condition, and add the
drain-progress fact that distinguishes the two cases:

- If the drain has made progress during this run, the backlog is a legitimate burst that
  exceeded the budget. Say so, and name the DAG width as the driver.
- If the drain has made NO progress at all, the consumer really is stuck. Say that.

`_Bridge` already tracks a high-water mark; add a drained counter next to it. The counter is
also the honest signal C3 asks for: a stuck consumer is one that never drained, not one that
is merely behind.

### 3.3 Not in scope

- **Bounding the DAG's dep fan-out.** It would keep the buffer small at the source, but it
  serializes node admission and changes the performance of every run. A separate decision.
- **Making `_eval` yield before it emits.** Same objection: a hot-path change to every run
  to fix a bound that is simply set too low.
- **An asynchronous observer protocol in url4.** The correct long-term shape, and far too
  large for this.

## 4. Acceptance criteria

1. A DAG whose single burst exceeds 8192 events completes. A deterministic test drives the
   real `_Bridge` through the real publish loop at a width that raises today.
2. Memory stays bounded: a producer that never stops still fails at the budget.
3. A consumer that never drains still fails the run, and the message says the consumer is
   stuck.
4. A burst that exceeds the budget fails with a message naming the width and the budget, not
   the consumer.
5. Span, cost, result and terminal events are never dropped. Only `Log` is.
6. The budget is readable from the environment, with the existing result caps as the model.

## 5. Open question for the owner

The 64 MB budget is a judgement call. It is 30x the widest burst measured and 1/16 of the
result hard cap. If the run pods have a tighter memory limit than that implies, name the
number and the spec takes it instead.
