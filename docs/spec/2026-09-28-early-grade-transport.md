# OME-932 — proposed early-grade transport

Status: design proposal following the IFEval proof; not implemented.
Base inspected: 3293550b (includes activity-log PR #1071).

## Decision proposed

Carry canonical typed case results through normal execution output, then observe those values for running scores. Do not make successful execution depend on logs or an observer-owned cache. Final aggregation consumes the typed results instead of re-running the grade hook.

This requires a production protocol migration beyond OME-932's original prohibition on expression/result/cache-identity changes. The proof does not remove that requirement. Approve the revised scope before changing production routes or published revisions.

## Interface and placement

Keep benchmark-specific grading in the existing ScoredPath adapter. Introduce a board-bound case-finalization interface in Engine that takes a completed case-execution outcome plus its authoritative selection and private grading material, and returns a canonical CaseResult. Bind the board explicitly at route installation; never infer which scorer to execute from activity text or an ambiguous outer expression.

For boards whose checking already finishes per case, call this interface after the candidate outcome and protected grading evidence are available. Do not use the earlier check or envelope-packing route as the universal point: it may lack the complete candidate/failure outcome. For Inspect, invoke the same result-observation contract when its existing async aggregate grade hook produces a CaseResult; moving Inspect judges before later answers is not necessary for updates after each judge finishes.

Reuse CaseResult as the typed payload. A versioned Engine-owned row envelope should identify the benchmark, revision and selected position alongside that payload so the receiving aggregate can reject cross-board, cross-revision and wrong-position rows. Use the existing CaseId type, not a new string normalization. A versioned board route must select its expected row schema; do not silently guess between old raw grading envelopes and new typed results.

The exact schema and method signature remain to be frozen by implementation tests. The observer receives an already-decoded CaseResult, not raw JSON; ordinary execution transport still necessarily serializes and validates data.

## Final aggregation responsibilities

- Validate the complete selection and incoming row identities, duplicate/unselected IDs and row count.
- Verify supplied case input/metadata against the authoritative selection; a matching ID alone is insufficient. Pydantic validation is structural, not evidence authenticity.
- Preserve existing per-board anonymous failure and missing-result policy. RowReader currently uses array position to assign anonymous errors. The singleton proof does not establish that this behavior survives a migration.
- Reduce the completed numeric-grade subset using the same board scorer in selected order.
- Reconcile grading accounting only at the final CandidateResult boundary.

Do not add a fallback that re-grades missing typed results: that can silently repeat paid calls. Invalid transport must be rejected; genuinely missing/failed case work follows the existing failure policy. A malformed later row can invalidate a run after earlier provisional scores were shown; the client must retain their provisional meaning and never promote them to final.

## Accounting

`grading_accounting.py:reconcile_candidate_grading_accounting` can revoke attribution when later evidence owners share a request key. Therefore early scoring facts and final accounting are different lifetimes. Preserve the existing final reconciliation against the run ledger, including clearing ambiguous attribution; do not call whole-candidate finalization on partial selections and do not treat serialized early accounting as authoritative.

Test two cases sharing a request key, retry costs, missing accounting, and cache hits. Provisional logs contain counts and score only, not evidence/accounting copies.

## Cache and replay

The inspected Engine connector handles model-response cache outcomes in `world/connector.py`, including zero current consumption for a served cache hit. Do not assume that a cached model response means the entire case endpoint was skipped. Test that path with real connector cache metadata.

Any whole-case or full-result replay must work from its serialized execution result without requiring an earlier in-memory callback. A full-result replay can legitimately go directly to the final score. Do not synthesize historical grading events or replay old costs as new spend.

Version the changed internal row contract and review the corresponding generated expression and benchmark protocol/revision identity. Update replay fixtures through the approved migration process only after proving unchanged prompts, grades, final reports and paid-call counts. Existing v1 envelopes must not be misread as v2 results.

## Rejected alternatives

| Alternative | Reason |
| --- | --- |
| Client extracts scores from activity logs | Logs are lossy and do not carry canonical scoring rules |
| Observer calls grade_case itself | Observation would execute work, potentially duplicate judging, and change semantics when disabled |
| Hidden run-local grade cache is required for final aggregation | Cache/replay or missed callbacks would break final results; execution correctness becomes ambient state |
| Publish aggregate-only snapshots for every board | Does not meet IFEval/DRACO's early-update requirement |
| Add benchmark semantics to URL4 | Engine already owns grading and final-result contracts |

## Verification gate before rollout

1. New row encode/decode tests: strict types, benchmark/revision/position mismatches, duplicates and malformed results.
2. Real two-case IFEval execution: pause candidate 2, observe case 1 score; one checker/grade call per case; full final payload parity.
3. Failure before case finalization, protected grading failure, refusal, missing row, and invalid later row preserve existing outcomes.
4. Model cache hit and serialized-result replay work with observation disabled; no extra calls or stale accounting.
5. DRACO and FrontierScience exercise different adapters; then run the full registry matrix.
6. Only after Engine transport/producer verification, add the separately scoped Client provisional-score consumer. Final results always override snapshots.

Assessment: this is the preferred design direction based on current source and the IFEval proof, not yet an end-to-end verified implementation. It is a shared execution/result refactor with observation layered on top, not merely a logging change.
