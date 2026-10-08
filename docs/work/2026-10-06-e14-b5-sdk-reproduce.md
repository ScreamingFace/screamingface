---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-06
finished: 2026-10-06
---

# e14-b5-sdk-reproduce — SDK sends the cache version, and `sf.reproduce`

## Intent

E14 PR B5 (spec `prd/cache-version-capture.md` C4, C13, C14 and `prd/reproduce.md` R1-R11, R16, R20,
R23, R24; contracts K3, K4, K7, K8). The SDK reads `cache.revision` and `cache.reproducible` from
the run summary, sends them with `answer_seed` on submit, and gains `sf.reproduce(score)`: it runs
the score's url4 again from its stored cache version, classifies the result, and records an exact
reproduction on the board. Engine (B3) and board (B4) are in this checkout; all HTTP is faked with
`httpx.MockTransport` and the existing test fakes.

## Planned changes

- `_core/ports.py`: `_RunOutcome.cache_revision`, `reproducible`, `cache_replay`.
- `_engine/contract.py`: read the three summary attributes beside `cache.hits`.
- `_evaluation/results.py`, `report.py`: `CandidateResult.cache_revision`, `reproducible`.
- `_scoreboard/leaderboards.py`: `_submission` sends the three fields when not None; `_decode_score`
  reads the B4 fields and `benchmark_revision`; private `_record_reproduction` (sync + async); the
  client-info dict becomes a shared helper.
- `leaderboard.py`: `LeaderboardScore` new fields.
- `_engine/transport.py`: `X-Cache-Replay` on the start call; the echo is the ack; a missing ack
  stops the run and raises `ExecutionError(code="replay_unsupported")`.
- `_evaluation/model.py`, `_evaluation/url4.py` (not in the plan; coordinator-approved): Candidate
  `cache_replay` field and `_with_cache_replay`; `cache_replay` keyword on `evaluate_url4_*`, which
  also checks the summary's `cache.replay`.
- New `_reproduction.py` (renamed from `reproduce.py`, coordinator-approved): `Reproduction`,
  `_classify`, the sync and async flow.
- `client.py`, `_default_client.py`, `__init__.py`: `reproduce` on both clients, `sf.reproduce`,
  export `Reproduction`.
- `tests/public_surface_snapshot.json`: regenerated. New tests only.

## Decisions recorded (coordinator answers, 2026-10-06)

- Q1: the two engine codes are declared in the engine and in the SDK mirror. `_classify` reads
  `failure.code`. In replay mode the summary carries `cache.replay`; a replay summary without it, or
  with another label, is `failed/replay_unsupported` (in addition to the start-response ack).
- Q2: touch `_evaluation/model.py` and `_evaluation/url4.py`, mirroring `answer_seed`.
- Q3: `failed/run_failed` is a non-empty `result.failures` that is not a replay code. Exceptions
  propagate as in `evaluate`, except `ExecutionError(code="replay_unsupported")`, which gives
  `failed/replay_unsupported` with `result=None`. A mismatched echo counts as missing.
- Q4: `complete` with `cache_revision` None is `not_reproducible/unknown`, no run.
- Q5: private `Leaderboards._record_reproduction` and the async twin. The board's 409
  (`run_id_conflict`, `not_reproducible`, visibility) and 422 `not_exact` go to `record_error`.
- Q6: module `_reproduction.py`; `Reproduction` exported from `__init__`; a test that `sf.reproduce`
  is callable.

## Test plan

New files only. PRD order: cv #14, #15; rp #1 (CHAR), #15 to #21, #23 (SDK half). Plus: decode and
validation of the new fields, the board field decode, both clients, `sf.reproduce` callable.

## Acceptance

- Gates green for `screamingface` with `--base e14-a2-sdk-metadata`.
- No existing test edited, except the regenerated surface snapshot.

## Approved test changes (append-only exception)

- `tests/public_surface_snapshot.json` regenerated with `UPDATE_SURFACE_SNAPSHOT=1` for the new
  public names (`reproduce`, `Reproduction`, the new `CandidateResult` and `LeaderboardScore`
  fields). Pre-approved by the coordinator.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `_evaluation/model.py` and `_evaluation/url4.py` (approved). New
  tests: `test_cache_version_capture.py`, `test_cache_version_submission.py`,
  `test_cache_replay_transport.py`, `test_cache_replay_evaluate.py`,
  `test_leaderboards_reproductions.py`, `test_reproduce.py`. `_report_primitives.py` needed no change:
  the two codes were already declared there.
- **Commits:** see `git log --oneline e14-a2-sdk-metadata..HEAD`.
- **Gates:** without `--skip-append-only`, only the append-only check fails, and it lists exactly
  `tests/public_surface_snapshot.json` (the approved regeneration) and `tests/_isolation_engine.py`
  (the approved helper extension, see below). With `--skip-append-only`: ruff, format, pyright,
  pytest (2466 passed, 26 skipped, coverage gate 95% met), notebooks, build and distribution checks
  all pass.
- **Skipped tests:** 26, none Postgres. 7 `tests/e2e/test_boards.py` (no recorded fixtures or
  prepared assets), 16 e2e replay lane (`SCREAMINGFACE_TEST_E2E` not set), 1
  `test_inspect_log_live.py` (`inspect_ai` not installed), 1 `test_url4_cloud_integration.py`
  (needs a real runner). The e2e lane spine test (rp #22) was not run; the in-process spine test
  `test_reproduce_review.py::test_submit_then_get_score_then_reproduce_is_exact_and_recorded` covers
  the same path against a stub Engine and a stub board.
- **Design-review round (coordinator, 2026-10-06; one round):**
  - Replay failure codes in the result prove replay mode: `_classify` and the url4 check classify by
    `replay_cache_miss` / `unknown_cache_revision` before `cache.replay` is required. Only a result
    with no replay code and no matching `cache.replay` is `failed/replay_unsupported`. Tests use
    realistic outputs (all-miss with no summary, K10 with no summary, neither).
  - The record POST sends the replay's `result.score` and `len(result.cases)`.
  - A stored score with no `benchmark_revision` is `not_reproducible/unknown` before any run. This
    replaces the earlier note that it classified as `benchmark_revision_changed`; `_classify` still
    compares literally, but `reproduce` never reaches it with such a score.
  - `_stamped(candidate, **changes)` iterates `fields(Candidate)`; the two stamps use it.
  - `reproducible_status` in `_report_primitives.py` is the one narrowing, used by `contract.py`,
    `leaderboards.py`, `leaderboard.py` and `report.py`; the `# type: ignore` is gone.
  - `reproduce` raises `TypeError` for anything but a `LeaderboardScore`, `UUID` or `str`.
  - `_unsupported`, `_judged` and `_recorded` are inlined.
  - The record path drops `client.version` when longer than 64 characters; submit is unchanged.
  - `ReproductionOutcome` is exported; the snapshot is regenerated again.
  - A failed stop after a missing echo: `_stop_own_run` now returns whether it stopped, and the
    transport raises `ExecutionError(code="replay_unsupported")` with the text "the run may still be
    running on the Engine" and a hint. `reproduce` returns `failed/replay_unsupported` and emits an
    `EvaluationWarning` with that text (`Reproduction` has no message field, so a warning tells the
    user).
  - Tests added: client-level async missing echo, the spine, and the review cases above.
  - Approved test-helper change (append-only exception): `tests/_isolation_engine.py` gained a
    `honour_replay`, `summary` and `result_body` set on `RunPlan` (all defaulted, so every existing
    plan behaves as before), a `replay_labels` record, the echo header, and `plan` and `replay`
    parameters on `_frame_for`. The gate lists it because five existing lines changed: the
    `_frame_for` signature and its call, and the frame 3 and frame 4 entries of its `kinds` table now
    read from locals. Their values are the same for every plan that sets none of the new fields.
- **Deviations:**
  - `_RunOutcome.cache_replay` (the summary's `cache.replay`) is an extra field, for the coordinator's
    "replay summary lacks the label" check (Q1). The check lives in `evaluate_url4_*`.
  - The ack check requires the echo to equal the label sent, not only to be present (Q3).
  - The transports start a run through a new `_start_run` method (sync and async) so the stop on an
    unacknowledged replay does not exceed the repo's complexity limits in `_run_reconnecting`.
  - `Reproduction` fields after `outcome` have defaults. `_record_reproduction` takes `result.score`
    through `typing.cast(float, ...)`: an exact outcome means it equals a stored float.
  - `LeaderboardScore` validates the new fields in a module helper `_reproduction_fields`, and
    `_submission` builds the cache fields in `_cache_version_fields` (both for ruff limits).
  - `CandidateResult` refuses a `cache_revision` without `reproducible` and a malformed label,
    mirroring the board (cv C10).
  - The submission tests (cv #15) were written before the code, but their RED run was not recorded
    before the commit.

## Frozen-copy rework (2026-10-08)

Spec: `docs/plan/2026-10-06-e14-reproducible-submission/F-B5-sdk-capture-reproduce.md` and
`docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` §5, §7. The cache-revision
design is gone from the stack. B5 now sends `capture=True` and reproduces over a frozen copy. New
commits sit on top of the earlier B5 commits. Engine (F-B3) and board (F-B4) are in this checkout;
their names were read from their code (`X-Capture`, `X-Replay-Frozen-Copy`, `capture.frozen_copy_id`,
`capture.status`, `capture.replay`, `frozen_copy_miss`, `frozen_copy_unavailable`; board fields
`frozen_copy_id`, `capture_status`).

### Changes

- `evaluate(..., capture: bool = False)` on `Client`, `AsyncClient` and `sf.evaluate`. It is threaded
  like `answer_seed`: `client.py` to `_evaluation/url4.py` (url4 path) and `_evaluation/runner.py`
  (Recipe path) to `Candidate.capture` through `_stamped`, then the transport sends `X-Capture: true`
  only when true.
- `Candidate.cache_replay` is now `Candidate.replay_frozen_copy`. `_stamped` refuses a Candidate that
  has both `capture` and `replay_frozen_copy` (`ValueError`), so no stamp can build one.
- Transport: the replay header is `X-Replay-Frozen-Copy`. The echo check uses the new name. A capture
  start has no echo check: an Engine that ignores `X-Capture` gives a result with no
  `frozen_copy_id`, which the SDK reads as "not captured".
- Run summary: `capture.frozen_copy_id`, `capture.status`, `capture.replay` go to
  `_RunOutcome.frozen_copy_id`, `capture_status`, `capture_replay`. Absent is `None`.
- `CandidateResult.frozen_copy_id` and `capture_status` replace `cache_revision` and `reproducible`.
  A copy id must be a lower-case UUID string, and it needs a `capture_status`. `to_dict` keys follow.
- `submit` sends `frozen_copy_id`, `capture_status` and `answer_seed` when set.
- `LeaderboardScore.frozen_copy_id` and `capture_status` replace `cache_revision` and `reproducible`.
- `_report_primitives.reproducible_status` is now `capture_status_value` (same narrowing).
- `sf.reproduce`: outcome table of design §7 in check order. Replay codes are `frozen_copy_miss` and
  `frozen_copy_unavailable`. Both also prove replay mode when `capture.replay` is absent. The record
  POST sends `frozen_copy_id` in place of `cache_revision`.
- Stale PRD ids (`K3`, `R24` and the like) were removed from the B5 comments, because the PRDs that
  carried them are superseded.

### Tests

- Renamed this PR's own test files (they are new against the base, so the append-only check does not
  see them): `test_cache_version_capture.py` to `test_capture_summary.py`,
  `test_cache_version_submission.py` to `test_capture_submission.py`,
  `test_cache_replay_transport.py` to `test_frozen_copy_transport.py`,
  `test_cache_replay_evaluate.py` to `test_frozen_copy_evaluate.py`. Fixtures and names in
  `test_reproduce.py`, `test_reproduce_review.py` and `test_leaderboards_reproductions.py` follow.
- Added: `X-Capture` is sent only when true (sync, async, real transport); `capture=True` reaches the
  Candidate on the url4 path and the Recipe path, sync and async; `capture` and a replay are mutually
  exclusive; the result, submit and board fields decode and validate; the two codes are declared in
  the SDK mirror and the two old codes are not; check order (miss before unavailable, unavailable
  before run_failed); a complete score with no copy id starts no run; the spine test now captures with
  `capture=True` and reproduces from the copy.
- Approved test-helper change (append-only exception, same as the first B5 round):
  `tests/_isolation_engine.py` now uses `X-Replay-Frozen-Copy` and `capture.replay`, keeps
  `replay_copies` (was `replay_labels`) and adds `capture_starts`.
- `tests/public_surface_snapshot.json` regenerated with `UPDATE_SURFACE_SNAPSHOT=1` (pre-approved).
  Diff: `capture` on the three `evaluate` signatures; `frozen_copy_id` and `capture_status` replace
  `cache_revision` and `reproducible` on `CandidateResult` and `LeaderboardScore`.
- TDD note: this was a rework in place. The old tests failed on the renamed names first (as the task
  expected). The new capture tests were written together with the code, and their RED run was not
  recorded separately.

### Deviations

- `_evaluation/runner.py` is not in the plan. It changed so that `capture=True` also works for Recipes,
  as `answer_seed` does (a private `_captured_candidates` beside `_seeded_candidates`). Without it the
  Recipe path would drop `capture` silently.
- `capture` and a replay are refused in `_stamped` (a `ValueError`). The plan says only that they are
  mutually exclusive.
- `_classify` keeps `run_failed` as "a non-empty `result.failures`". Replay codes at case level and
  `frozen_copy_unavailable` at any level are caught by earlier checks. A candidate-level
  `frozen_copy_miss` therefore reads as `run_failed`, which is a failed run too.

### Gates

- With `--skip-append-only`: ruff, format, pyright, pytest (2487 passed, 26 skipped, coverage gate
  95% met), notebooks, build and distribution check all pass.
- Without it: only the append-only check fails, and it lists `tests/_isolation_engine.py` and
  `tests/public_surface_snapshot.json` (the two approved changes above).
- Skipped tests (26, none Postgres): 7 `tests/e2e/test_boards.py` (no recorded fixtures or prepared
  assets), 17 e2e replay lane (`SCREAMINGFACE_TEST_E2E` not set), 1 `test_inspect_log_live.py`
  (`inspect_ai` not installed), 1 `test_url4_cloud_integration.py` (needs a real runner). The e2e
  spine test (rp #22) did not run. The in-process spine test covers the same path.

### Design-review round (coordinator, 2026-10-08; one round, "accept with fixes")

- Stub engine (`tests/_isolation_engine.py`, approved helper): the plan's `capture.*` summary keys
  are sent only to a start that carried `X-Capture`. A replay run states only `capture.replay`. The
  spine test now checks that the replay result has no `frozen_copy_id` and no `capture_status`: the
  copy id comes from the capture run.
- New tests: `capture=True` on the async Recipe path; module-level `sf.evaluate` forwards `capture`
  on both branches (a complete URL4, and Recipes with a benchmark), true and default. The module
  level function is sync only, and the async Client door is covered by its own tests.
  A removed forwarding fails a test.
- New tests: a candidate-level `frozen_copy_unavailable` with no case failures is
  `failed/frozen_copy_unavailable` and passes the statement check. A candidate-level
  `frozen_copy_miss` is `failed/run_failed` (accepted rule, also pinned in `_classify`).
- `_engine/contract.py`: `_summary_label` is now `_summary_copy_id`. Capture parse errors say
  "capture summary". The fields stay on `_CacheSummary`; its docstring says so.
- `LeaderboardScore.frozen_copy_id` is normalised as the board does (`str(UUID(value))`). An invalid
  value is refused at construction (`ValueError`, or `TypeError` for a non-string), so `reproduce`
  never sends a malformed header. A decoded board score with a bad id is a `LeaderboardError`. The
  `_capture` docstring in `report.py` now says that `CandidateResult` is stricter than the board:
  it refuses a non-canonical spelling and does not normalise it.
- Decision: with `capture=True` and no `capture.status` in the run summary, `evaluate` emits an
  `EvaluationWarning` ("the Engine did not capture this run; it cannot be reproduced (Candidate
  'name')"). The result keeps `frozen_copy_id=None` and `capture_status=None`. A stated `partial`
  status without a copy id does not warn. The check is `_warn_if_not_captured` in
  `_evaluation/results.py`, called through `_conclude_evaluation` in `_evaluation/runner.py` from
  the url4 and Recipe paths (sync and async). Tests cover warn, no warn, and both paths.
- `runner.py` comment over the two stamps names both `answer_seed` and `capture`. The async
  `evaluate` docstring mentions `capture`. Finding 9 left as is. Finding 10 is fixed in the engine's
  later commits.
- Gates: with `--skip-append-only` all green (pytest: 2508 passed, 26 skipped, coverage gate met).
  Without it, only the append-only check fails, on `tests/_isolation_engine.py` and
  `tests/public_surface_snapshot.json` (the two approved changes). Skips are the same 26 as above.

## Rebase onto main (2026-10-08)

- The stack was rebased onto `origin/main` `4cd063445` (87 new commits on main).
- Conflict in `report.py`: main added the `scores` argument to `CandidateResult`. The constructor
  keeps `scores` and adds `frozen_copy_id` and `capture_status`.
- Conflict in `tests/public_surface_snapshot.json`: regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` at each commit that changed
  it, never merged by hand.
- Gates for stack `screamingface` pass against `e14-a2-sdk-metadata` (`--skip-append-only`; the
  approved test edits are unchanged).
