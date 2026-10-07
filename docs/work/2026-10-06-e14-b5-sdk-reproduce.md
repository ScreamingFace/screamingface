---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-10-06
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
