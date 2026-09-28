---
ticket: OME-1088
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1088 — make the run queue's replica count configurable

## Intent

The queue stream's replica count is a hardcoded constant (`QUEUE_REPLICAS = 3`) with a
`RunQueue(replicas=...)` seam that no composition root passes. A single-node NATS — which is
what the chart's own bundled subchart ships, and what local dev and the CI conformance job
run — refuses `replicas > 1` outright with `ServerError 10074`. The error is not a
`BadRequestError`, so `ensure_stream` does not tolerate it and the worker's claim loop retries
it forever: every run is refused and the deployment is dead. Found by manual e2e deployment
of the OME-1086 stack on the `sf` kind cluster (2026-09-03 findings, B2).

This unit lands the setting half of the fix — a `Settings` field and a single-node-safe
default. The call sites that construct `RunQueue` do not exist on this branch yet; they are
wired on the branches that introduce them (OME-1089 worker, OME-1090 App factory), and the
chart renders the value at OME-1092.

Default is **1**, not the spec's 3, by owner decision (2026-09-03): it matches the bundled
single-node subchart, and the per-run event streams are already declared at JetStream's
default of 1 replica (`adapters/jetstream.py`), so a 3-replica queue on an otherwise
1-replica bus hardens only the queued-not-started window. Multi-replica durability is
OME-1093's scope.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` — `QUEUE_REPLICAS`
  3 → 1; correct the module docstring and the `replicas` parameter comment, which both
  describe the constant as a production-3/test-1 split that no longer holds.
- `apps/screamingface-engine/src/screamingface_engine/config.py` — new
  `run_queue_replicas: int = Field(default=runner_queue.QUEUE_REPLICAS, ge=1)`.
- `apps/screamingface-engine/tests/unit/test_run_queue_replicas_setting.py` — NEW file
  (tests are append-only; no prior test is touched).

## Test plan

- The setting defaults to the module constant, so the two cannot drift.
- The default is single-node-safe (`== 1`) — the invariant this unit exists to protect.
- `URL4_CLOUD_RUN_QUEUE_REPLICAS` env var sets the field (the chart's transport).
- Boundary: `0` and a negative value are refused by validation.
- `RunQueue` declares the stream with the replica count it was given, and defaults to the
  constant when none is passed.

## Acceptance

- A `Settings` built with no environment yields `run_queue_replicas == 1`.
- `RunQueue(..., replicas=n)` passes `num_replicas=n` to `add_stream`.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:** as planned, plus one unplanned edit to a prior test (see Deviations).
  - `src/screamingface_engine/runner_queue.py` — `QUEUE_REPLICAS` 3 → 1 with the rationale
    anchored; module docstring no longer states a literal replica count; the `replicas`
    parameter comment now describes a deployment knob rather than a test-only affordance.
  - `src/screamingface_engine/config.py` — `run_queue_replicas: int = Field(default=..., ge=1)`.
  - `tests/unit/test_run_queue_replicas_setting.py` — NEW.
  - `tests/unit/test_run_queue_stream_config.py` — EDITED (approved; see Deviations).
- **Commits:** `fix(engine): make the run queue's replica count configurable (OME-1088)`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN
  (ruff check · ruff format --check · pyright · check_layering · pytest --cov ≥80).
  Three red iterations before green, all `E501`/format nits in prose I had rewrapped.
- **Deviations:**
  1. **A prior test was edited, with owner approval.**
     `tests/unit/test_run_queue_stream_config.py` asserted `num_replicas == 3` and said "3
     replicas" in two docstrings. Changing the default made that assertion false. Per the
     append-only rule this is a Confidence-Gate decision, so it was put to the owner as an
     explicit choice against the alternative (keep the code constant at 3 and default only
     the chart to 1, touching no prior test). The owner chose to change the code default and
     approved this specific edit on 2026-09-03. Gates were therefore run with the sanctioned
     `--skip-append-only`; no gate was weakened and every other gate ran in full. An
     `AIDEV-NOTE` at the edited test records what changed and why.
  2. **The default is 1, not the spec's 3.** `docs/spec/2026-09-02-OME-1086-*` still says 3.
     The spec is now stale on this point and should be amended when the stack's PR bodies are
     updated — an owner action. Rationale is anchored at `QUEUE_REPLICAS`; multi-replica
     durability belongs to OME-1093.
  3. **RED was reasoned, not observed as a separate run.** The new tests were written before
     the production change, but their first execution happened after it, because the fresh
     worktree's `uv sync` was still in flight at the moment RED would have been run. Each new
     assertion targets behavior that did not exist beforehand (the field itself, its `ge=1`
     validation, the changed default), so the failing-for-the-right-reason property holds by
     construction — but it was not witnessed, and that is worth saying plainly.

## Follow-ups surfaced (not in this unit)

- `ensure_stream` treats a PERMANENT broker refusal as retryable. `ServerError 10074` can
  never succeed on the broker that returned it, yet it escapes to the claim loop, which logs
  at WARNING and retries every second forever; the only other signal is `pull_failures_total`.
  A permanent stream-declaration failure should fail fast and loudly instead. Not folded in
  here to keep this unit to one focused change — worth its own ticket.
