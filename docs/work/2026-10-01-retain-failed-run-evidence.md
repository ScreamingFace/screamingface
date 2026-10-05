---
ticket: OME-946
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# retain-failed-run-evidence — skip the 60 s subject purge for failed runs

## Intent

A failed deployed run's frames are its only diagnostic record, and both reclaim paths purge
the run's subject 60 s after it ends. Per the 2026-10-01 re-scope of OME-946: skip the purge
when the run ended `failed` or `timed_out`, and let the shared `url4-events` stream's 24 h
`max_age` reap it. Successful (and `stopped`) runs keep the 60 s reclamation (cost +
prompt-content exposure). `discard=OLD` on the 1 GiB stream can still evict a retained failed
run sooner under load — documented, not fought.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine/evidence_retention.py` — the one
  rule: a subject whose terminal frame is `failed`/`timed_out` is retained; an unreadable tail
  (`QueueReadError`) falls back to the purge (status quo). Shared leaf (layering gate).
- `worker/supervisor.py` `_schedule_reclaim` — consult the rule after the grace, before the purge.
- `runner/main.py` `run_and_reclaim` — optional keyword `retain` predicate (default: none →
  unchanged behaviour); `_run_process` wires the rule over the raw publisher's `last_frame`.
- NEW tests: `tests/unit/test_failed_run_evidence_retention.py`.

## Test plan

- Rule: `failed`/`timed_out` terminal → retain; `succeeded`/`stopped`/non-terminal/None → purge;
  `QueueReadError` → purge.
- Supervisor: a run whose subject ends in `Terminated(failed)` / `timed_out` (child-published, or
  the worker's own classified frame for a non-zero exit) is NOT reclaimed after the grace; a clean
  run IS reclaimed after the grace.
- Runner: `run_and_reclaim(..., retain=...)` skips `delete_stream` when retain says so, still
  sleeps the grace first, still re-raises the run's own exception, and a raising predicate does
  not mask the run outcome.

## Acceptance

- A failed run's subject outlives the grace period; a successful run's subject is purged at 60 s.
- All prior tests unmodified and green; `run_gates.py screamingface-engine` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `evidence_retention.py` (new), `worker/supervisor.py`,
  `runner/main.py`, `tests/unit/test_failed_run_evidence_retention.py` (new, 17 tests). No prior
  test touched.
- **Commits:** the `feat(engine): retain failed-run evidence …` commit carrying this ledger.
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN (append-only, ruff check,
  ruff format, pyright, layering, pytest + coverage ≥80).
- **Deviations:**
  - Failure is decided by the subject's terminal frame (`failed`/`timed_out`), not by the process
    exit/raise: `lifecycle.run` returns normally on failure, so exit code / raise cannot see it.
    Consequence: a runner whose `run_once` RAISED without a failed terminal frame on the subject
    is still purged (the prior test `test_the_stream_is_reclaimed_even_when_the_run_fails` pins
    that and stays unmodified).
  - `run_and_reclaim` gained an optional keyword `retain` predicate (default None = old
    behaviour) rather than reading the tail itself, so the prior runner tests' recorder (no
    `last_frame`) stays valid untouched.
  - Unreadable tail (`QueueReadError`) → purge (pre-OME-946 behaviour), to never extend a
    possibly-successful run's prompt-bearing frames.
  - Found and fixed during GREEN: an early `return` inside the reclaim `finally` swallowed the
    run's own exception; replaced with if/else (test pins it).
