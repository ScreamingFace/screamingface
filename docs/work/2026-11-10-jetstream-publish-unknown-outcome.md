---
ticket: OME-1859
stack: screamingface-engine
status: done
started: 2026-11-10
finished: 2026-11-10
---

# jetstream-publish-unknown-outcome — an unknown publish outcome keeps its caller's slot

## Intent

A JetStream publish is at-least-once: the broker can store a run's message while the publish
times out, while nats-py buffers it during a reconnect, or while the start is cancelled.
`QueueJobRunner.schedule()` read every failure as "not queued": it freed the caller's admission
slot and answered 503, while a stored run executed outside the per-caller cap and read
`not_found`. Found in the #1648 review; it predates E5 P1 (OME-1785).

Spec: `docs/spec/2026-11-10-jetstream-publish-unknown-outcome.md`. Plan:
`docs/plan/2026-11-10-jetstream-publish-unknown-outcome.md`. An unknown outcome holds the
attempt's reservation; the caller's retry of the topic is admitted past it and counted once;
the run's terminal frame when observed (a Run cancel's tombstone included), the run's lifetime
or the one-hour lease frees it.

The first approach on this branch (re-send the publish, wait for it after a cancel) was replaced
after the #1732 review: the re-send cannot settle a send nats-py buffered during a reconnect, and
the wait after a cancel skipped the mount handler's stop of its run. A second one, where a retry
took the held reservation over, was replaced after a review round found races between attempts
sharing that reservation; each attempt now holds only its own.

## Planned changes

The task list is the plan's. Paths under `apps/screamingface-engine/`:

- `src/screamingface_engine/adapters/queue_runner.py`: an unknown outcome holds the attempt's
  reservation; the cap counts a held start once, adds nothing for a hold beside a landed
  attempt, and never refuses a retry for its own holds; a hold ends with the run's terminal
  frame when observed, its lifetime, or the lease.
- `src/screamingface_engine/rest/routes.py`, `runner_queue.py`: comments on what a 503 means.
- `CHANGELOG.md`; `.github/workflows/screamingface-engine-tests.yml` (the NATS job runs the new
  real-broker test).

## Test plan

- `tests/unit/test_queue_schedule_unknown_publish.py`, as the plan lists them.
- `tests/integration/test_run_queue_publish_settles_nats.py` (real NATS, CI's NATS job).
- Prior tests: one edited, byte-pinned in `.claude/test-change-approvals/OME-1859.json`.

## Acceptance

- Both of the reviewer's repros keep the slot; a stored run is never left uncounted.
- Engine gates green in CI; targeted tests, ruff, pyright, layering and the append-only check
  green locally.

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (under `apps/screamingface-engine/` unless noted):
  - `src/screamingface_engine/runner_queue.py`: `PublishOutcomeUnknown`, raised from the run's
    own send only.
  - `src/screamingface_engine/adapters/queue_runner.py`: `_Hold`, `_HELD_SLOT_SLACK_S`;
    `_settle_failed_publish` holds or releases; `_cap_count`; `_prune_holds` and `_present`.
  - `src/screamingface_engine/rest/routes.py`: the 503 comment and log line.
  - New tests: `tests/unit/test_queue_schedule_unknown_publish.py`,
    `tests/integration/test_run_queue_publish_settles_nats.py` (added to the NATS job's lists in
    `.github/workflows/screamingface-engine-tests.yml`).
  - Prior test edited: `tests/unit/test_queue_admission.py` (the cancel mid-publish test),
    byte-pinned in `.claude/test-change-approvals/OME-1859.json`.
  - `CHANGELOG.md`; spec, plan and this ledger; the OME-1859 mirror.
- **Commits:** the first approach (`e4bae817f`, re-send and wait-after-cancel) and its docs
  commit, then the rework (`06dd21ad3`) and one commit per review round (rounds 1 to 9).
- **Gates:** locally, per round: ruff, ruff format and pyright on touched files, the layering
  check, the append-only check, and the touched and nearby test files (110 passed at the last
  round). The full Engine suite passed locally up to round 3 (8697 passed, 350 skipped); CI runs
  the gates and the NATS job.
- **Deviations:**
  - Replaced twice after review: the re-send could not settle a send nats-py buffered during a
    reconnect; a retry taking the held reservation over raced every path sharing it.
  - A plain stop tombstoning a held topic, and a mount call stopping its own run after a 503,
    were added and then removed (round 5): both kept growing edge cases, and neither path is
    needed for the accounting.
  - Nine review rounds; the last found no high-severity issue. Items left as they are are in
    the spec's Rejected and Out of scope sections.
  - A `/simplify` pass after the last round removed ending holds on a landing and on a
    tombstone: the cap count already gives the same count, and the run's terminal frame, a
    tombstone included, frees a hold when observed. Duplicate tests went, and the
    `RunQueue.publish` tests moved beside its other publish tests.
