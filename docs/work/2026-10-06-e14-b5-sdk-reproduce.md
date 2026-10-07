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
