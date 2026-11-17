---
ticket: OME-1932
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# parked-case-results — park each Case of the Candidate Result on disk (unit 2 of memory fix 3)

## Intent

Unit 1 (OME-1835, PR #1855) removed the whole `str`, url4 copy and bytes copy of the Candidate
Result. The peak that remains is the list of full `CaseResult` objects that the aggregate holds
while it marks, finalizes and writes the result (about 30 KiB per Case for a 5-member Fusion).
This unit parks each Case's wire JSON in the run's Case-result store as it is marked, scores on
light projections, and writes the result body from the parked text. The bytes on the wire and
the SDK contract do not change. The goal is aggregate memory that is flat in the Case count.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md` ("Unit 2 — parked Cases").
Plan: `docs/plan/2026-11-16-streamed-candidate-result.md` ("Unit 2 — parked Cases").

This branch is stacked on `OME-1835-streamed-result-delivery` (unit 1, not merged yet). It is
rebased onto `origin/main` when PR #1855 merges.

## Planned changes

See the plan, "Unit 2 — Files". One correction to the plan: unit 1's `deliver_result` and
`deliver_result_sync` accept only a `CandidateResult`, so they must also accept a `ResultBody`
(the `ParkedResultBody`). The writer and the spool do not change.

## Test plan

See the plan, "Unit 2 — TDD order". Score identity first, on today's code. The invariant under
test: the delivered bytes equal unit 1's bytes, and every score equals today's score.

## Acceptance

- Engine gates green; all existing aggregate tests unchanged.
- Aggregate growth per Case is flat between N=500 and N=2,000, and is a small multiple of one
  projection. The stage tables below, measured again after the change.

## Baseline measured before the unit (2026-11-16, unit 1 at `5a1260b49`)

`scripts/bench/report_memory.py`, tracemalloc, peak KiB per Case above the start of the
aggregate; synthetic MMLU-Pro, stub gateway. Gates green (`--base
origin/OME-1835-streamed-result-delivery`); inspect lane 3,046 passed.

| Stage | 1 model N=500 | 1 model N=2,000 | Fusion N=500 | Fusion N=1,000 | Fusion one emoji N=300 |
|---|---|---|---|---|---|
| Candidate Result bytes | 3.8 | 3.8 | 9.9 | 9.9 | 9.9 |
| `CaseResult` list held (marking done) | 10.9 | 10.5 | 31.4 | 30.9 | 31.0 |
| + finalize (peak of the run) | 11.7 | 11.6 | 32.4 | 32.0 | 31.7 |
| spool delivered | 11.6 | 11.5 | 32.3 | 31.9 | 31.6 |
| held until the run ends | −1.6 | −1.7 | −2.0 | −2.4 | −2.8 |

The peak is the full `CaseResult` list: about 3 × the result bytes per Case.

## Measured after the unit (2026-11-16, this branch)

Same harness and units. New stage lines: `2p` (Cases parked, projections held) and `3p`
(builder finished: the light result and its head).

| Stage | 1 model N=500 | 1 model N=2,000 | Fusion N=500 | Fusion N=1,000 | Fusion one emoji N=300 |
|---|---|---|---|---|---|
| Candidate Result bytes | 3.8 | 3.8 | 9.9 | 9.9 | 9.9 |
| marking done (parked; projections held) | 5.4 | 5.2 | 5.2 | 4.3 | 4.9 |
| builder finished (peak of the run) | 6.3 | 6.2 | 5.7 | 5.2 | 5.4 |
| spool delivered | 5.1 | 4.9 | 4.4 | 3.9 | 4.2 |
| held until the run ends | −1.2 | −1.2 | −1.8 | −2.3 | −2.1 |

Peak per Case, unit 1 → unit 2: 11.6 → 6.2 (1 model, N=2,000); 32.0 → 5.2 (Fusion, N=1,000);
31.7 → 5.4 (one emoji). Before memory fix 3 (on `main`): 14.3, 39.1, 77.6. The peak no
longer grows with the result size per Case: it is the scoring projections (about 5 KiB per
Case, the same for 1 model and for the 5-member Fusion) and the same at N=500 and N=2,000.

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (all under `apps/screamingface-engine/`):
  - New: `benchmarks/result_builder.py` (`CandidateResultBuilder`, `ParkedResultBody`,
    `ParkedCase`, `CaseParkingError`), `benchmarks/scoring_projection.py` (moved from
    `activity/progress.py`; `attempts` → `[]`; returns a projection unchanged).
  - Changed: `benchmarks/aggregation.py` (`finalize_candidate_result` runs on the builder);
    `benchmarks/case_result_store.py` (`read_text`); `grading_accounting.py`
    (`GradingAccountingView`, `grading_accounting_view`, `reconcile_case_accounting_text`);
    `benchmarks/shared_grading/benchmark_aggregation.py` (`aggregate_body_async`, shared
    marking loop); `benchmarks/grading_endpoints.py` (`deliver_result*` accept a `ResultBody`);
    `screamingface_engine_inspect/single_shot.py` (parked faces used by the hosted routes);
    `activity/progress.py` (imports the projection); `scripts/bench/report_memory.py`
    (stages `2p`, `3p`).
  - New tests: `tests/unit/test_{scoring_projection,scoring_projection_parity,
    case_result_store_text,deliver_result_body,parked_aggregate,parked_late_accounting,
    result_builder,parked_result_review_fixes}.py`, `tests/unit/inspect/test_{parked_result_hosted,
    parked_result_memory,report_memory_parked_stages,scoring_projection_whole_run_parity}.py`.
- **Commits:** on branch `OME-1932-parked-case-results` (stacked on
  `OME-1835-streamed-result-delivery`); the PR is squash-merged.
- **Gates:** engine gates green (`--base origin/OME-1835-streamed-result-delivery`; the
  append-only check passes, so no prior test changed); inspect lane 3,055 passed (3,046 before).
- **How it was built:** tiered-build workflow (Opus plan, Haiku and Opus implementers). The
  first run stopped on a question (four unit 1 tests captured `HeldResultBody`). Owner
  decision: change the two capture tests in PR #1855 itself (`e7df21058`, capture at
  `write_result_body`) and keep the held faces (Option B). The second run built six waves;
  its last check stopped it before gates and review (a "no files changed" check on a
  measurement wave). The orchestrator then ran the gates, an Opus design review
  (ACCEPT-WITH-FIXES, R1–R11, no blocker), a fix round (R1/R2 by Opus, R3–R10 by Haiku), an
  Opus fix check, and the last fixes. A mutation check confirms the R1 test fails without the
  fix.
- **Deviations:**
  - Option B (owner): `aggregate_result_async`, `_judged_aggregate_result` and the dict faces
    still return a held `CandidateResult` (from the same builder: one finalize). New parked
    faces (`aggregate_body_async`, `benchmark_aggregate_body_async`, `_aggregate_body`,
    `_judged_aggregate_body`) carry the hosted production path.
  - The plan said unit 1's endpoint does not change; `deliver_result` and
    `deliver_result_sync` had to accept a `ResultBody` (dispatch: `Mapping` → today's string;
    `CandidateResult` → held body; else a `ResultBody`).
  - R1 (review): the final grading accounting is a frozen `GradingAccountingView`, taken on
    the run loop in `finish_body` (the same point as the held reconcile). The spool's worker
    thread only reads it. The held reconcile uses the same view and rule (R2).
  - A protected test requires `benchmark_aggregation.finalize_candidate_result is
    aggregation.finalize_candidate_result`, so the held face still calls it; it runs on the
    builder in held mode. `aggregation.finalize_candidate_result` imports the builder lazily
    (`result_builder` imports `aggregation`).
  - `_park` wraps `UnicodeEncodeError`, `OSError` and `CaseResultStoreError` in
    `CaseParkingError` (a `RuntimeError`, never `benchmark_unavailable`); other `ValueError`s
    are data bugs and propagate as before unit 2.
  - Score identity was proved on the pre-move projection with a scratch swap: the parallel
    wave had already moved the code when the parity test ran, so its RED step was not seen.
- **Follow-ups (not in this unit):**
  - R6: `incremental.py` `finish_result` (the MedXpert early-grade route) still holds every
    full Case; the two aggregate faces repeat one outline. One private `_aggregate(keep=…,
    finish=…)` would remove both.
  - R7: move `SelectedCase`, `CandidateScore`, `Scorer`, `policy_cases` into a leaf module
    so `aggregation` needs no lazy import.
  - `reconcile_case_accounting_text` parses each parked Case when a grading registry is bound
    (CPU on the worker thread only; memory stays at one Case).
