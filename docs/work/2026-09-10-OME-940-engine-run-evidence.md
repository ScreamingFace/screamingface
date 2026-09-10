---
ticket: OME-940
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-940 — Log engine run identity and terminal evidence on the control plane

## Intent

Rung 4a of the correlation ladder, and the P0 half of durable evidence: a run's whole
diagnostic record (the NATS frame stream) is deleted 60 s after it ends
(`DEFAULT_STREAM_GRACE_S = 60.0`, still true on `main`), so a failed deployed run is not
reconstructable after ~2 minutes. Two control-plane log lines put the essentials into
`kubectl logs`, which keeps them for the pod-log window.

## What the issue says vs what the code now is

The issue was written before `#822` retired the k8s Job adapter, and three of its premises no
longer hold. Recording them rather than quietly working around them.

**F1 — `adapters/k8s.py:268` does not exist.** The Job adapter is gone; the schedule sites are
now `adapters/inprocess.py:196` and `adapters/queue_runner.py:269`.

**F2 — a terminal line already exists, and it is emitted for the WRONG runs.**
`runner/main.py::_log_terminal` already builds a rich line carrying `trace_id`, `dropped_logs`
and `high_water`. But:

```python
if summary.outcome != "succeeded":
    return          # <- the rich line, trace_id included, is SUCCESS-ONLY
```

A **failed** run gets only the terse `run finished topic=… outcome=failed code=… type=…`,
which carries **no trace id at all**. That is exactly inverted from this issue's purpose — the
failed run is the one whose evidence is needed, and it is the one that loses it.

**F3 — and in local mode that function never runs.** `_log_terminal` is reached from
`runner/main.py`'s Job entrypoint. `InProcessJobRunner.schedule` calls `lifecycle_run(...)` in
a task directly and never goes through it, so a local-mode run emits no evidence line by any
path. This is why ladder rung 4a xfails today, and why the fix has to live in the **adapters**
— the one place both modes pass through, which is also what the issue means by "control
plane".

## Design decisions

**D1 — both lines live in the two adapters, not in `runner/main.py`.** Following F3: the
adapters are the only common point. `runner/main.py`'s existing lines stay as they are — they
are the Job-process view and are not wrong, merely absent in local mode.

**D2 — the schedule line states `trace_id=pending` when the caller sent none.** At schedule
time the id genuinely is not known yet: `url4.streaming.lifecycle.run` mints one when the
inbound traceparent is absent, and that happens after the adapter has returned. Writing
`trace_id=none` would be a lie by omission (there will be an id), and inventing one here would
produce a second id that correlates with nothing. `pending` says what is true, and the terminal
line closes the loop with the real value.

**D3 — the terminal line's trace id comes from the run's own summary/frame, never re-derived.**
Same rule `OME-967` and `OME-1119` follow: the id quoted must be the one that actually
travelled.

**D4 — this also fixes the `run_scope(None)` gap I filed on this issue earlier.**
`runner/main.py:477` binds the log context from `parse_traceparent(env)`, which is `None`
whenever the caller sent no traceparent — so those runs' process lines carry `topic=` and no
`trace_id=`, even though the run has one. The ladder's client always originates a traceparent,
so rung 4a would go green while the deployed no-inbound-traceparent path stayed anonymous.
**Rung 4a is therefore asserted for BOTH shapes**, inbound-present and inbound-absent.

## Open question — raised, not decided

**The issue says "do not log the raw topic — it is a bearer capability (JWT `sub`); digest
only." Both halves of that need checking, and I did not follow it.**

*The premise is inaccurate as written.* The topic is the **subject** of a capability, not the
capability. `auth/jwt.py:39-45` signs `{"sub": topic}`, and `rest/routes.py:509` reads the
topic **out of already-verified claims** — every path requires a signed token, which cannot be
minted without the secret. Knowing a topic therefore grants nothing.

*And the codebase has since standardised on the opposite.* `logs.py:96` renders
`topic={context.topic}` onto **every** `screamingface_engine` log line via `RunContextFilter`
(`OME-1069`), and `reaper.py`, `runner/main.py` boot/world/terminal lines all log it raw.
Emitting a digest here alone would make these two lines the only ones that cannot be grepped
against every other line about the same run — strictly worse for the debugging this issue
exists to serve.

So these lines log `topic=` like their neighbours. If the owner wants digests, that is a
**repo-wide** change (starting with `RunContextFilter`) and its own work item — not something
to introduce inconsistently here.

## Planned changes

- `src/screamingface_engine/adapters/inprocess.py` — schedule + terminal evidence lines.
- `src/screamingface_engine/adapters/queue_runner.py` — the same two, same field order.
- `src/screamingface_engine/runner/main.py` — emit the evidence line for **every** outcome
  (F2), and bind the log context to the resolved trace id (D4).
- Tests as below.

## Test plan

RED first:

- **A terminated run leaves a control-plane evidence line** — asserted for `succeeded`,
  `failed` and `stopped`, because success-only is the defect being fixed.
- The evidence line carries the run's trace id **when the caller sent one and when it did
  not** (D4) — the second is the case that would otherwise stay anonymous in deployment.
- A scheduled run leaves an identity line linking topic ↔ trace_id ↔ job name.
- Both adapters emit the same field set — local and deployed must not diverge.
- No line is emitted outside a run; boot lines stay byte-identical.
- Ladder rung 4a flips green; **its strict xfail marker is deleted in this PR**.

## Acceptance

- A failed run leaves a greppable trace id in the engine's process log, in both modes.
- Rung 4a green; rung 4b still xfail.
- `run_gates.py screamingface-engine` green, `check_layering.py` included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `run_evidence.py` (new), `adapters/inprocess.py`, `adapters/queue_runner.py`,
  `runner/main.py`, `tests/unit/test_run_evidence_lines.py` (7 new tests), plus three prior
  tests and the ladder.
- **Commits:** `feat(engine): log run identity and terminal evidence on the control plane`
  (sha at squash-merge).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — **ALL GREEN** (ruff, ruff
  format, pyright, **check_layering**, `pytest --cov --cov-fail-under=80`): **2707 passed, 9
  skipped**. `run_gates.py screamingface --skip-append-only` — **ALL GREEN**. Ladder:
  **3 passed, 2 xfailed** — rung 4a flipped green (rung 3 is `OME-938`/#898, not on this branch).
- **Deviations:**
  - **D2 was replaced by a better design during implementation.** The ledger planned
    `trace_id=pending` at schedule, because `lifecycle.run` mints the id internally and after
    the adapter returns. The adapter can simply **mint it itself** and pass it in, which
    `lifecycle.run` then adopts. One change collapses three problems: the id is known at
    schedule (no `pending`), the terminal line always has the real value, and
    `job_env.TRACEPARENT` is now always set — which fixes the `run_scope(None)` gap (D4) as a
    consequence rather than as separate surgery. It is also more correct by W3C: a service with
    no inbound trace context starts the trace at its edge, not inside its run loop.
  - **A test caught a real bug in the first implementation: the outcome cannot come from the
    asyncio task.** `lifecycle.run` CATCHES a failing run and publishes
    `Terminated(status="failed")` rather than re-raising, so the task completes normally and
    `task.exception()` is `None` for a run that failed outright — `outcome_of(task)` reported
    `succeeded` for every failure, the one case this evidence exists to record. Replaced with
    `TerminalWatch`, a transparent publisher proxy reading the run's own terminal FRAME, with
    the task kept only as a fallback for runs that died before publishing anything.
  - **Three prior tests changed, all retargeted to the invariant their NAME states, none
    weakened** — assertions went 22 → 23 and 36 → 39, i.e. every change ADDED coverage:
    - `test_a_malformed_traceparent_is_dropped_rather_than_forwarded` asserted the env key was
      ABSENT, which was how "do not forward garbage" was achieved. The adapter now mints a
      replacement, so the key is present; the test now asserts the malformed value does not
      travel AND that what does is valid — the same intent, checked directly.
    - `test_log_terminal_omits_cost_and_cache_for_a_failed_run` asserted no `run summary` line
      at all, which is why the only line carrying `trace_id` was success-only. It now asserts
      the line EXISTS for a failure and omits cost/cache — exactly what its name claims.
    - The ladder's rung 4a marker was deleted.
  - **The issue's "digest only, the topic is a bearer capability" instruction was NOT followed,
    deliberately.** Verified both halves: `auth/jwt.py` signs `{"sub": topic}` and every route
    reads the topic out of ALREADY-VERIFIED claims, so knowing one grants nothing — it is the
    subject of a capability, not the capability. And `logs.RunContextFilter` puts `topic=` on
    every engine log line (`OME-1069`), as do the reaper and the runner's boot lines. Digesting
    here alone would make these the only two lines that cannot be grepped against the rest of
    the run's output. Raised in the ledger as a repo-wide decision rather than applied
    inconsistently.
  - `PLR0911` (too many returns) was satisfied by splitting `_outcome_without_a_frame` out, not
    by suppression — and the split is meaningful: "with a terminal frame" vs "without".
