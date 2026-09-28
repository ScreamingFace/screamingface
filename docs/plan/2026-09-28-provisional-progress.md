# OME-932 — implementation and verification plan

Status: implementation and verification in progress.
See docs/spec/2026-09-28-provisional-progress.md for evidence and timing limitations.

## 1. Characterize before changing behavior

Create a registry-driven matrix covering all eight built-ins and 24 Inspect registrations. Exercise each board's actual aggregate route with deterministic model substitutes and prepared fixtures. Include solo and fusion candidates at limits 1 and 2; verify model substitutions traverse the actual judge adapter, not only direct grade_case calls. Fail coverage when a shipped registration lacks a test or explicit unsupported declaration.

For each board, record typed cases, canonical final score/metrics, rendered expression, model/judge request counts, failures and paid accounting. Test every nonempty partial subset in selected order against that board's existing scorer. Include ContractEval positive-only/negative-only/mixed subsets and both HealthBench policies. Empty gradeable subsets yield no provisional score, not zero.

## 2. Prove the observation seam

Add shared typed terminal-outcome observation with a no-op default. Tests must cover successful grading, refusal with a numeric grade, absent grade, malformed/missing row, missing material, hook failure, omitted CaseResult, cancellation and duplicate delivery. Prove exactly-once counting without changing final missing-result handling.

Exercise synchronous aggregation, async imported judging, worker-context propagation, concurrent candidates and nested executions. Observer/scorer failures must not change execution outcomes. Never suppress the real grading error or cancellation. Confirm final reports, expressions, request counts and accounting match the step-1 baseline.

## 3. Prove activation and snapshot contract

Test registered aggregate plus literal selection, and silent decline for unknown, missing, malformed, duplicate, conflicting or nonliteral discovery. Assert no filesystem/network/dataset access at observation opening.

Test monotonic snapshot revisions, selected-order scoring, bounded counts, optional score, run isolation, privacy allowlist, dropped-log recovery from the next cumulative snapshot and anonymous failure replacement without double counting. Do not equate terminal progress with successful grading.

Test rate/coalescing policy on large synthetic runs: avoid scoring every prefix; flush latest state while the bridge is still open. Verify bounded memory and no extra model calls. Completion and interruption must preserve the last truthful state; interrupted runs must never claim all selected cases finished.

## 4. Integration proof and review

Run the full deterministic board matrix through the real executor and structured Log decoder. Assert final cumulative gradeable count/score equals final CandidateResult where observation is supported. Verify no premature 'complete' and no dependence on log arrival order. Retain existing baseline progress tests.

Inspect a FrontierScience solo/fusion run and DRACO solo/fusion run at limit 2 against the preview Engine after deterministic gates pass. Reuse permitted credentials/assets; agree any paid live execution separately. These demonstrations supplement, not replace, the all-board matrix. A fast deterministic board may legitimately emit only a final snapshot.

Run repository-required Engine gates, replay parity and review before a draft PR. Recheck main and pending activity changes at implementation time. Do not mark OME-932 Done merely because planning or tests exist.

## 5. Separate client follow-up

Consume the versioned structured snapshot; do not infer scores from activity text. Display the running numeric score without an extra provisional label (user-directed), retain existing active-case display semantics, and replace with authoritative final results. Test dropped snapshots, no-gradeable outcomes and independently finishing candidates. This is outside the Engine-only ticket.

## Approval decision

Approve aggregation-phase progress as the first scope, or require earlier scores during answering and investigate a deeper grading/execution refactor first. The current audit supports the former; it does not establish the latter is a small change.

## Revised acceptance after user clarification

For a two-case IFEval/DRACO run, block case 2 after case 1's authoritative grading evidence is complete. The client must already show the provisional score for case 1 while case 2 remains blocked. An aggregate-only implementation fails this acceptance test.

For FrontierScience, block the second judge after the first judge finishes. The first judge's completed grade must update the table while the second is pending. Answer completion alone must never update a grading score.

Before the implementation steps above, design and characterize an earlier canonical case-finalization boundary for the built-ins that currently collect evidence before folding grades. Reuse that result in final aggregation rather than grading again. Verify both solo/fusion and failures, including a failed case that produces no grade: completed coverage may advance while score stays unchanged.

Client scope: add separate provisional score/graded-count/revision state; use it only until an authoritative CandidateResult exists. A late provisional event must never overwrite the final score. Test score zero, no gradeable cases, stale/out-of-order events, interrupted evaluation and independent candidates. Keep active case numbering separate from graded-count coverage.

Do not proceed with the narrower aggregation-only scope as though it fully meets the requested UX. First resolve whether early canonical finalization fits the existing endpoint/result contracts and the ticket's no-expression-change constraint.

## Next bounded design proof

Before broad implementation, exercise the proposed single-case grading interface on IFEval and DRACO (early evidence) plus FrontierScience (async judge). These represent genuinely different adapters. Compare typed grades, final scores, errors and call/accounting counts with existing execution. Include cached/replayed execution and case failure before the shared case-execution endpoint. Keep runtime experimentation isolated and obtain implementation approval before modifying Python.

Reject the design if it requires benchmark-specific client logic, a second grader in an observer, or a progress-dependent result cache. If carrying the typed grade requires an envelope/expression change, record that migration explicitly and revise OME-932's scope rather than hiding it in logging work.

## First draft implementation slice

Expose `ScoredPath.iter_case_results(raw_rows, *, selected_cases, grading_material, case_metadata=None)` as an async iterator of canonical typed results. It owns the existing row validation and selected-order iteration. Final aggregation consumes this same interface, so it is exercised by all shipped boards. Preserve omitted results for finalizer reconciliation. This establishes incremental consumption during grading; moving built-in grade production earlier and publishing structured snapshots are explicitly subsequent work. No claim of completed notebook behavior in this draft.

## IFEval execution proof

Extract only IFEval's existing ScoredPath construction into a reusable factory. A test-local execution harness invokes the real checker and case-envelope routes, consumes one canonical grade per completed case, then finalizes the typed results. A gated second candidate proves timing, counters prove no duplicate checks/grade calls, and the old batch path is the payload-parity oracle. This deliberately leaves production expression migration for a subsequent change; it cannot by itself enable table updates.

## Transport direction after the proof

See docs/spec/2026-09-28-early-grade-transport.md. Proposed production design carries a typed grade in a versioned execution row; final aggregation validates and reduces it, and accounting remains final-run reconciled. This supersedes any suggestion that an observer-only change can deliver early built-in scores. Confirm the protocol-migration scope before implementing it; then follow the transport/failure/cache acceptance matrix in that proposal.

## Approved production IFEval slice

User approved production wiring on 2026-09-28. Add a versioned typed result row and a board-bound case-result endpoint after preserved execution. Change the canonical IFEval build to call it and final aggregation to consume those rows. Advance the IFEval protocol revision. The existing raw aggregate Python function remains a parity oracle; the production route must not accept both formats heuristically. New tests exercise actual generated execution and no-regrading replay. Snapshot/test migrations require the separately requested existing-test approval.

## Live preview iteration

Implement the scalar snapshot port and optional activity accumulator; invoke from IFEval's case-result endpoint. Add a pure Client snapshot parser/state, then connect existing score/qualifier properties without changing layout. Verify Engine timing through real URL4 logs and Client widget rendering before refreshing the local notebook. This bounded IFEval integration does not claim all-board early grading support. No new URL4 fields or expression change.

## All-board implementation iteration
1. Cover real built-in routes and blocked async grading with new progress tests; publish from shared aggregate consumption.
2. Generalize early canonical-result production and typed-result transport for the remaining built-in families, preserving case positions and board-specific metadata/failure mappings.
3. Migrate revisions/expression and replay fixtures only with existing-test approval; compare canonical outcomes and model request counts.
4. Verify the registry, including every imported board, run stack gates and refresh the preview. Aggregate-only progress is an intermediate step, not completion of built-in early scoring.

### Review correction
Add a real MedXpert batch-versus-early grading-failure regression, then validate decoded results against base selection before checking optional enrichment. Run full Engine gates and update the draft. Public single-case API and IFEval orchestration consolidation remain separate cleanup.
