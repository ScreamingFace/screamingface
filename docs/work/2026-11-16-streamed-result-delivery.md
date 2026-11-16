---
ticket: OME-1835
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# streamed-result-delivery — deliver the Candidate Result without building it whole (unit 1 of memory fix 3)

## Intent

Large runs are killed with `memory_budget_exceeded` right after the last Case (`OME-1885`:
5-model Fusion on full MMLU-Pro, 2,926 MB; `OME-1887`: production blocker). The end of a run
builds the whole Candidate Result as a dict tree, one `str`, a url4 copy of that `str` and a
bytes copy. With one wide character in any answer the `str` is 4 bytes per character, and the
peak is 8 × the result bytes. This unit streams the result one Case at a time into an artifact
sink and passes a small reference through url4. The bytes on the wire and the SDK contract do
not change. Unit 2 (parked Cases) follows after this unit's numbers.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md`.
Plan: `docs/plan/2026-11-16-streamed-candidate-result.md` (units 0 and 1).

## Planned changes

See the plan, "Unit 1 — Files".

## Test plan

See the plan, "Unit 1 — TDD order". The invariant under test: the delivered bytes equal
`compact_json(CandidateResult.as_payload())` of the previous code.

## Acceptance

- Engine gates green; existing aggregate, result-delivery and e2e replay tests unchanged.
- The stage table below, measured again after the change: no dict-tree, `str` or bytes stage,
  and nothing result-sized held until the run ends.

## Baseline measured before the unit (2026-11-16, `main` at `4679d5c6a`)

tracemalloc, KiB per Case above the start of the aggregate; synthetic MMLU-Pro, stub gateway.

| Stage | 1 model, N=2,000 | 5 members + synthesizer, N=1,000 | same, one emoji in one answer, N=300 |
|---|---|---|---|
| Candidate Result bytes | 3.8 | 9.9 | 9.9 |
| `CaseResult` list held | 10.0 | 30.4 | 30.8 |
| + finalize | 11.3 | 31.6 | 31.8 |
| + dict tree | 14.3 | 39.1 | 39.2 |
| `str` + url4's copy | 8.1 | 23.5 | 77.6 |
| bytes + store write | 5.8 | 17.3 | 76.7 |
| held until the run ends | 2.0 | 7.3 | 37.0 |

Also checked: a result assembled one Case at a time, each Case through a JSON round trip, is
byte-identical to today's (120 Cases, 720 operations, 1,218,105 bytes).

## Measured after the unit (2026-11-16, this branch)

`scripts/bench/report_memory.py`, same harness and units as the baseline. The url4 hand-off
carries an 87-char reference; the result goes to the artifact store in chunks.

| Stage | 1 model, N=2,000 | 5 members + synthesizer, N=1,000 | same, one emoji in one answer, N=300 |
|---|---|---|---|
| Candidate Result bytes | 3.8 | 9.9 | 9.9 |
| `CaseResult` list held | 10.2 | 30.5 | 31.6 |
| + finalize (peak of the run) | 11.6 | 31.9 | 32.7 |
| spool delivered (peak) | 11.5 | 31.8 | 32.6 |
| `str` + url4's copy | — (none) | — (none) | — (none) |
| bytes + store write | — (none) | — (none) | — (none) |
| held until the run ends | −1.7 | −2.5 | −1.8 |

Peak: 14.3 → 11.6 (1 model), 39.1 → 31.9 (Fusion), 77.6 → 32.7 (one emoji). The one-emoji
case no longer doubles. The peak that remains is the `CaseResult` list (unit 2).

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (all under `apps/screamingface-engine/`):
  - New: `artifacts/spool.py` (`ResultSpool`), `benchmarks/result_body.py` (`ResultBody`,
    `HeldResultBody`, `write_result_body`; now owns `compact_json`),
    `scripts/bench/report_memory.py` (unit 0).
  - Changed: `artifacts/{ports,filesystem,s3,delivery,__init__}.py` (`StreamingArtifactWriter`,
    `ArtifactSink`, `result_too_large_message`); `benchmarks/grading_endpoints.py`
    (`deliver_result`, `deliver_result_sync`); `runner/{executor,main,operation_capture}.py`
    (redeem in `build_result`, one spool per run); the aggregates in
    `shared_grading/{benchmark_aggregation,incremental,incremental_routes,serving}.py`,
    `medxpert/{aggregate,runtime}.py` and `screamingface_engine_inspect/single_shot.py` now
    return the `CandidateResult`; `error_text.py` (comment).
  - New tests: `tests/unit/test_{result_body,result_spool,result_spool_wiring,build_result_spool,
    deliver_result,filesystem_artifact_sink,s3_artifact_sink,result_too_large_message,
    medxpert_aggregate_result,aggregate_result_methods,streamed_aggregate_routes}.py` and
    `tests/unit/inspect/test_{report_memory_script,streamed_result_memory,streamed_result_hosted,
    streamed_result_surrogate,streamed_judged_aggregate}.py`.
- **Commits:** on branch `OME-1835-streamed-result-delivery`; the PR is squash-merged.
- **Gates:** engine gates green (`run_gates.py screamingface-engine --base origin/main`);
  inspect lane 3,046 passed (3,035 before the unit). One gate run hung in the coverage
  pytest step (all workers idle at 0% CPU for 27 min; stopped, no stack available without
  root). Two later runs (unit suite verbose: 9,364 passed in 26 s; full gates) did not hang.
  Watch for it in CI.
- **How it was built:** tiered-build workflow (Opus plan and review, Haiku implementers, one
  fix round). Review verdict ACCEPT-WITH-FIXES; findings F1–F13; all fixed except F7 and F9
  below.
- **Deviations:**
  - The append-only test gate forbids lowering `_AGGREGATE_KIB_PER_CASE` in
    `test_case_result_memory.py`. The tighter bounds are in the new file
    `test_streamed_result_memory.py` (Fusion 40.5, one emoji 39.5, held 1.0 KiB/Case). The old
    path fails all three bounds (48.95, 83.46, 7.1/36.3).
  - The spool errors are local to `artifacts/` (the layering gate forbids a url4-engine import
    there); the runner maps them to `result_too_large` and `result_spool_unredeemed`.
  - The spool is made only when the store has `open_sink` (`StreamingArtifactWriter`); a test
    double store keeps today's path.
  - The plan said a lone surrogate fails the run in `build_result`. It does not, on this branch
    or on `main`: `CaseResultStore.append` turns it into a Case failure (`missing_case_row`)
    first. `test_streamed_result_surrogate.py` pins that behaviour.
  - **F7 (open, owner decision):** `result_spool_unredeemed` is not in `ENGINE_ERROR_CODES`.
    Adding it means a change to `ALLOWLISTED_CODES` in `test_terminal_error_detail.py`, a
    protected constant that records a security decision.
  - **F9 (accepted as documented, owner decision):** if the run ends during the final commit,
    the committed artifact has no ticket. The store's TTL sweep or bucket lifecycle removes it.
    See the KNOWN WINDOW comment in `artifacts/spool.py`.
