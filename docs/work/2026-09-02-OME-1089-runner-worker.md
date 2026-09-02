---
ticket: OME-1089
stack: screamingface-engine
status: in_progress
started: 2026-09-02
finished:
---

# OME-1089 — Add the runner worker: slot pool, subprocess supervision, deadlines, drain

## Intent

The pool that replaces the Jobs — the piece that makes the deployed footprint
constant. A new `worker` mode of the existing CLI: a slot pool that claims runs
from the OME-1088 queue and forks the existing run entrypoint as a supervised
child process, so the crash domain stays one run and `runner/main.py` is
untouched. The worker owns the hard deadline wall that replaces
`activeDeadlineSeconds`, the in-progress heartbeats that keep a 16-hour run from
looking abandoned, and the drain path. Each child is spawned under its own
`RLIMIT_AS`, or a single over-allocating run triggers a Pod OOM and kills its
co-tenants — which would void the reason for choosing subprocess isolation.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/worker/__init__.py`,
  `loop.py`, `supervisor.py` (new) — claim loop, supervisor, heartbeat task,
  hard wall, drain handler.
- `apps/screamingface-engine/src/screamingface_engine/cli.py` (modify) — the
  `worker` mode beside `serve` and `run`.
- `apps/screamingface-engine/src/screamingface_engine/config.py` (modify) —
  `worker_slots`, `drain_grace_s`, `worker_io_capacity`, per-run memory budget.
- `.claude/scripts/check_layering.py` (modify) — the worker half's rule: may
  import the serving half and `runner_queue`, must import nothing from the run
  half.
- Tests: `tests/unit/test_worker_*.py`, `tests/integration/test_worker_spine.py`
  (new).

## Test plan

- RED: a message whose topic already has a terminal frame is acked and never
  spawns a child.
- RED: slot accounting never exceeds `worker_slots`; fetch batch equals free
  slots.
- RED: child exit classification — exit 0 (worker adds nothing), non-zero,
  signal, and 137 each produce a named terminal frame from the worker.
- RED: a child hung past `deadline_s + STREAM_GRACE_S + margin` gets SIGTERM
  then SIGKILL, and a terminal frame is published.
- RED: `in_progress()` heartbeats keep a long child's message unredelivered
  past `ack_wait`.
- RED: a child spawned with a per-run `RLIMIT_AS` that allocates past it dies
  alone; the worker and its siblings survive.
- RED: drain — on SIGTERM the worker stops pulling, in-flight children survive
  to `drain_grace_s`, then terminate with a `worker_draining` reason.
- RED: a message whose capability has expired is acked with a `queue_expired`
  terminal frame and no child.

## Acceptance

- `screamingface-engine worker` mode exists; the image stays one artifact with
  modes.
- Children are spawned under `RLIMIT_AS` via an exec wrapper, not
  `preexec_fn`.
- Engine stack gates green (cov >= 80); the layering gate has a third half.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/worker/__init__.py` (new) — the
    worker half's package.
  - `apps/screamingface-engine/src/screamingface_engine/worker/loop.py` (new) — `Worker`
    (claim loop, slot accounting, drain, signal handling) and the `run_worker` composition
    root.
  - `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py` (new) —
    `RunSupervisor`: dedupe, queue-expiry, spawn, heartbeats, hard wall, exit
    classification, named terminal frames.
  - `apps/screamingface-engine/src/screamingface_engine/worker/exec_wrapper.py` (new) —
    sets `RLIMIT_AS` then execs `screamingface-engine run` in place (never `preexec_fn`).
  - `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` (modify) —
    `last_frame()` on `_JetStreamConnection` (the worker's dedupe/post-exit check).
  - `apps/screamingface-engine/src/screamingface_engine/config.py` (modify) —
    `worker_drain_grace_s`, `worker_io_capacity`, `worker_memory_budget_bytes`; the slot
    count reuses the existing `run_queue_worker_slots` (no duplicate field).
  - `apps/screamingface-engine/src/screamingface_engine/cli.py` (modify) — the `worker`
    mode beside `serve` and `run`.
  - `.claude/scripts/check_layering.py` (modify) — the worker half's rule: may import the
    serving half and `runner_queue`, must import nothing from the run half.
  - Tests: `tests/unit/test_worker_claim.py`, `tests/unit/test_worker_child_memory_cap.py`,
    `tests/integration/test_worker_spine.py` (new); `tests/unit/test_cli.py` (modify —
    worker dispatch + no-run-half-import probe).
- **Commits:** `feat(engine): add the runner worker (OME-1089)` — see `git log -1` for the
  sha (the ledger is amended in the same commit, so a literal sha here would be one amend
  stale by construction)
- **Gates:** `uv run ruff check` clean · `uv run ruff format --check` clean ·
  `uv run pyright` 0 errors · `check_layering.py` OK (three halves) ·
  `uv run pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q`
  → 2321 passed, 91.73% coverage.
- **Deviations:**
  - The plan's `worker_slots` setting is NOT a new field: the worker reads the existing
    `run_queue_worker_slots` (the value `max_ack_pending` is derived from), so the
    worker's concurrency and the queue's ack-pending bound cannot disagree.
  - The worker's `worker_io_capacity` is written onto every child's env as
    `URL4_CLOUD_IO_CONCURRENCY`, overriding the message's value — the worker is the
    authority on how wide a run may fan out (the fair-share gate cannot span processes).
  - `capability_expired` is defined as the run's deadline having elapsed since the message
    was published (`now - published_at >= deadline_s`) — the "executed late" case; the
    worker needs no new setting for it.
  - The drain phase sets a `_terminating` event before SIGTERMing children, so a child
    that ignores SIGTERM is SIGKILL'd after `kill_grace_s` instead of hanging the drain
    until its hard wall.
