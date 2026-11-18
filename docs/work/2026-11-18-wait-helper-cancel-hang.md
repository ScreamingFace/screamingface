---
ticket: OME-1962   # filed at PR-open on 2026-11-18 (bug: Triage, unassigned, no epic)
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-18
finished: 2026-11-18
---

# wait-helper-cancel-hang — the sync wait helper must end when the disconnect check swallows a cancel

## Intent

`wait_terminal_or_gone` (`rest/routes.py`) holds a request until the terminal frame of the run
arrives, or until the caller disconnects. It is used by the sync `GET /?q=` and by the mount
calls. The helper starts a poll task that calls `request.is_disconnected()` each 0.5 s. When the
helper ends, it cancels the poll task and then waits for it with no time limit.
Starlette's `Request.is_disconnected()` opens an `anyio.CancelScope` that is already cancelled.
If the cancel from the helper arrives while the poll task is in that scope, the scope exit can
swallow the cancel. Then the poll task continues, the wait in the helper does not end, and the
request handler hangs after the run ended. In a test (no disconnect) the test does not end. This
is a probable cause of Engine pytest runs that hang with idle xdist workers (seen 2026-11-17).
This unit proves the defect and makes the helper end in bounded time on each exit.

## Planned changes

- New: `apps/screamingface-engine/src/screamingface_engine/rest/caller_watch.py`: the race
  between a wait and the disconnect of the caller, with a bounded reap of the poll task.
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py`: `wait_terminal_or_gone`
  calls the new module. The names `wait_terminal_or_gone` and `WAIT_GONE` stay importable from
  `routes.py` (`rest/mounts.py` imports them). No bulk is added to `routes.py`.
- New test: `apps/screamingface-engine/tests/unit/test_wait_terminal_or_gone.py`.
- No change to a prior test. No change to the signature
  `is_disconnected: Callable[[], Awaitable[bool]]`. No new dependency.

## Test plan

Write these tests first. They must fail on the `origin/main` code, and they must not hang.

- Deterministic, with a fake `is_disconnected` that swallows ONE cancel and returns False:
  - exit (a): the terminal frame arrives; the helper returns the frame in bounded time;
  - exit (b): the calling task is cancelled; the helper ends in bounded time and the cancel
    is passed on (the calling task is cancelled, not completed).
- A fake that swallows EACH cancel and does not return: the helper returns in bounded time
  and writes a warning (the helper must not depend on a well-behaved callable).
- The real Starlette `Request.is_disconnected` (installed Starlette and anyio): show that the
  swallow is real, with a bounded loop on the alignment between the terminal frame and the poll.
- No task stays alive after the helper returns. No "Task exception was never retrieved" message.
- Contract of the helper (direct tests): terminal frame, bound passed (`None`), disconnect
  (`WAIT_GONE`) within 1 s (PRD 02 §4).

## Acceptance

- Each test for the defect fails on the `origin/main` helper for the correct reason (the helper
  does not end in the time limit of the test), then passes. The contract tests, and the
  alignments that do not put the cancel in the cancel scope, pass on `origin/main` by design.
- All prior tests pass and are not changed.
- `run_gates.py screamingface-engine --base origin/main`: all gates green, no gate skipped.
- The same defect pattern is searched for in `apps/screamingface-engine/src`; each place is
  recorded below.

## Outcome (fill at the end — required before COMMIT)

- **Root cause (proved):** `anyio` 4.14.2, `CancelScope.__exit__`. The poll task is in
  `Request.is_disconnected()` (Starlette 1.3.1). The scope is cancelled, so `anyio` calls
  `task.cancel()` on the poll task. If the cancel from the helper arrives after that call and
  before the task runs again, the two cancels become one `CancelledError` that has the `anyio`
  message. The scope exit swallows it. The check answers False, the poll continues, and the
  unbounded `asyncio.gather` in the `finally` of the helper does not return.
- **Real swallow reproduced:** yes, and it is deterministic (Python 3.13.15, starlette 1.3.1,
  anyio 4.14.2). With a real `starlette.requests.Request` on the `origin/main` helper: the
  terminal frame at 0 and at 1 event-loop turns after the start (2 of 8 alignments), and a
  cancel of the caller at 2 turns (1 of 8 alignments). Turn 0 is a run that ended before the
  wait started.
- **RED:** 6 failed, 16 passed, no hang (15.0 s) on the `origin/main` helper:
  `test_terminal_frame_ends_the_wait_when_the_check_swallows_one_cancel` ("the helper did not
  return after the terminal frame"), `test_caller_cancel_ends_the_wait_when_the_check_swallows_one_cancel`
  ("the helper did not end after the cancel of its caller"),
  `test_wait_is_bounded_when_the_check_ignores_each_cancel` ("its reap of the poll has no
  bound"), `test_terminal_frame_ends_the_wait_with_a_real_starlette_request[0]` and `[1]`,
  `test_caller_cancel_ends_the_wait_with_a_real_starlette_request[2]`.
- **The fix:** `rest/caller_watch.py`, `first_or_gone`. (1) The poll loop reads a `released`
  event after each check, so a swallowed cancel ends the loop in the same event-loop turn, with
  no delay. (2) `_reap_poll` cancels the poll at most 4 times and waits at most 0.25 s after
  each cancel (1 s in total), then writes a warning and returns. (3) A done-callback retrieves
  the exception of each task. (4) The wait task is Engine code: it gets one cancel and the
  helper waits for its end with no bound, as before. `WAIT_GONE`, the return shape, the 0.5 s
  poll and the signature of `wait_terminal_or_gone` did not change.
- **Actual files:** as planned. New `rest/caller_watch.py` (98 lines), `rest/routes.py` (22
  lines less), new `tests/unit/test_wait_terminal_or_gone.py` (24 tests), this ledger. No prior
  test changed.
- **Mutation check (not committed):** each of 5 changes to `caller_watch.py` made a test fail:
  no `released` check (7 failed), one cancel only (1), no exception retrieval (1), an unbounded
  reap (2), a swallowed cancel of the caller (8).
- **Stability:** the new file with `test_rest_sync_hold.py` and `test_mount_routes.py`, 25 runs
  with `-n 4 --dist worksteal`: 0 failures, before and after the review changes.
- **Review (read-only agent, 2026-11-18):** no blocker. Applied: the tests do not use wall-clock
  limits near a real sleep; the `released` check and the second cancel in the reap are pinned;
  a failed wait is tested directly.
- **Same pattern in other places:** `is_disconnected` has no other caller in
  `apps/screamingface-engine/src`. The two `anyio.CancelScope` uses (`rest/cache_entries.py`,
  `community_cache/aigateway.py`) are shield scopes with no cancel-then-wait. Not changed, for a
  new unit: a cancel that arrives in the event-loop turn where an httpx (`anyio.fail_after`)
  time limit fires can become a `TimeoutError`; candidate places that cancel a task and wait
  with no bound are `worker/loop.py:314`, `runner/executor.py:1131`,
  `benchmarks/shared_grading/benchmark_aggregation.py:1228`, `adapters/inprocess.py:585`. This
  was not reproduced and it is a different trigger (a time limit, not a scope that is always
  cancelled).
- **Commits:** one code commit on branch `OME-1962-wait-helper-cancel-hang` (first name: `wait-helper-cancel-hang`),
  `fix(engine): end the sync wait when the disconnect check swallows a cancel`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main`: `ALL GATES GREEN` (append-only
  check, ruff check, ruff format, pyright, layering, pytest with coverage; no gate skipped).
  Two runs, 81 s and 64 s. No run hung.
- **Deviations:** (1) The helper moved to a new module, because `routes.py` is much larger than
  450 lines. (2) Three tests change `_REAP_ROUND_S` or `DISCONNECT_POLL_S` of the new module, so
  the RED run was made with the same tests before those lines were added. (3) A disconnect
  check that ignores each cancel and does not return leaves its poll task alive after the
  helper returns (with a warning). That task ends when the check returns. No design can end such
  a task. (4) The worker stopped at the commit, by order of the caller. The calling session then
  filed the Linear bug OME-1962 (Triage, not assigned, no epic, Irina and Kevin tagged), renamed
  the branch to `OME-1962-wait-helper-cancel-hang`, wrote the `docs/tasks` mirror and opened
  the PR. The Linear MCP connector was not signed in; the owner chose the Linear CLI.
