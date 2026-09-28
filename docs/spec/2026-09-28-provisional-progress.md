# OME-932 — provisional progress investigation

Status: proposal; implementation not approved. Source audit only, not runtime proof.

Audited origin/main df6e9b92d1a55fb7c3a898164c82fea117522d5c on 2026-09-28.
Issue: https://linear.app/openmined/issue/OME-932/publish-terminal-benchmark-progress-and-provisional-scores

## Finding

A shared Engine implementation is feasible for the 32 shipped registrations (eight built-ins and 24 Inspect boards). All use ScoredPath. Their scorers can operate on nonempty subsets, but executable characterization is required before claiming compatibility. Future external plugins are not automatically covered.

The important limitation is timing. `benchmarks/protocol.py:benchmark_protocol` collects case evaluations before invoking the aggregate. `benchmarks/spine/scored.py:ScoredPath.aggregate_async` creates typed CaseResults inside that aggregate. Observing that boundary provides intermediate scores during aggregation, not necessarily while answers are being generated. Imported model-judged boards can expose meaningful progress there; deterministic reducers may finish too quickly to display intermediate updates. Some built-in judge work already happens before this boundary.

Do not promise early scores during answering without a separate execution-design change. Re-running grading in an observer would violate the issue's no-extra-work contract.

## Coverage and scoring evidence

Paths below are under apps/screamingface-engine/src/.

| Registrations | Canonical scoring source | Verification requirement |
| --- | --- | --- |
| DRACO, DRACO 3-pass | screamingface_engine/benchmarks/draco/grade.py, draco_scorer | Headline and axis metrics; preserve pass accounting |
| IFEval | screamingface_engine/benchmarks/ifeval/grade.py, _ifeval_score | Strict/loose prompt and instruction metrics |
| HealthBench worst30, professional | screamingface_engine/benchmarks/healthbench/grade.py and spine/exam.py | Preserve each variant's mean/clipping policy |
| GDPval text | screamingface_engine/benchmarks/gdpval/grade.py and spine/exam.py | Preserve exam scorer and invalid-verdict handling |
| MedXpert | screamingface_engine/benchmarks/medxpert/aggregate.py, _accuracy | Numeric grade eligibility and rounding |
| ContractEval | screamingface_engine/benchmarks/contracteval/aggregate.py, _confusion_matrix_score | Recompute canonical F1 from subset; never average case scores |
| All 24 Inspect boards | screamingface_engine_inspect/single_shot.py, scored_path and _accuracy | Deterministic and model-judged hooks, including FrontierScience |

Inspect inventory from screamingface_engine_inspect/boards.py: gsm8k, mmlu, arc_easy, arc_challenge, commonsense_qa, paws, boolq, mmlu_pro, winogrande, race_h, aime24, aime25, musr, wmdp_bio, wmdp_chem, wmdp_cyber, hellaswag, lab_bench_litqa, lab_bench_suppqa, lab_bench_dbqa, lab_bench_protocolqa, lab_bench_seqqa, lab_bench_cloning_scenarios, frontierscience.

## Proposed shared boundary

1. Add an optional fault-isolated observation boundary for already-typed terminal CaseResults in the shared scored path. Cover its failure ladder as well as successful grade_case returns. Do not parse activity text or raw JSON again.
2. Preserve canonical missing-result materialization. Today omitted results become failures only in `benchmarks/aggregation.py:finalize_candidate_result`; they must be counted once when that canonical failure exists, not guessed earlier.
3. Keep candidate/run state isolated and deduplicate by selected case identity. Retain selected order for scoring even if future grading becomes concurrent.
4. Reuse the exact board scorer and canonical eligibility predicate (`grade is not None and grade.score is not None`). Do not assume only status=scored contributes. Extract a shared pure helper if necessary to prevent predicate drift.
5. Do not invoke finalization per snapshot: it would turn pending cases into missing failures and invoke grading-accounting reconciliation. Final CandidateResult remains authoritative.
6. Emit privacy-minimal cumulative structured Logs through the existing bridge. Proposed payload concepts: schema version, revision, benchmark identity, selected count, terminal count, gradeable count, optional provisional headline score. Exact field names, failure counts and loss/replacement semantics need contract tests before freezing. No answers, prompts, IDs, judge reasoning, rubric text, or arbitrary board metrics in public snapshots.
7. Follow the issue's trusted activation rule: inspect the rendered expression for one registered aggregate and a literal selected count; decline ambiguous or invalid input. Current observer factories take no expression, so add a small generic run-preparation seam in Engine composition. Keep benchmark interpretation in the adapter, not the generic executor or URL4 SDK. Opening observation must perform no dataset or network I/O.
8. Coalesce snapshots and flush the latest state before run closure. Repeated whole-prefix scoring can be quadratic, particularly where scorers inspect checks. Bound recomputation frequency, not just log emission. Preserve normal execution and final results if observation fails.

## Constraints and scope

OME-934, OME-1097, OME-1100 and OME-1101 are Done; OME-932's older prerequisite text is stale. Do not revive old PR #692. Pending activity work is separate and must be reconciled with whichever main revision implementation uses.

No new URL4 syntax/Event kind, expression changes, retries, judge calls, cache changes, grading-ledger changes or client-side scoring. Existing terminal-Span progress remains intact. Client rendering is a separate follow-up under OME-887; Engine support alone does not update notebook scores.

Recommended first scope: shared aggregation-phase progress for all shipped boards, with honest optional provisional scores. If scores while answering is a requirement, stop and redesign the execution boundary before implementation.

## Follow-up: clarified user requirement

The user wants the candidate table's score to update after each case completes grading, not merely several quick snapshots immediately before the final result. This supersedes the recommendation to accept aggregation-phase updates as sufficient for every board.

Additional source findings:

- `packages/screamingface/src/screamingface/_ui/evaluation_state.py:_CandidateProgress.score` returns only `result.score`; `score_available` requires a final result. There is no provisional-score state here. `candidate_result` reconciles a completed candidate independently, but does not handle partial case results.
- IFEval's `definition.py:_build` invokes CHECK_ROUTE and CASE_EVALUATION_ROUTE within each case iteration. Its `case_evaluation.py:graded_record` validates those check records; `grade.py:aggregate` later constructs canonical grades through ScoredPath. Earlier evidence exists, but an activity completion is not itself a validated grade.
- DRACO's `grade.py:_grade_case` folds the collected verdict/check evidence into the canonical case grade during aggregate. A progress observer must not invent a parallel version of this fold.
- Inspect's `single_shot.py:board_aggregate_async` invokes the canonical scored path, including model-judged grade hooks. Per-case updates during that phase would track actual judge completion without moving judging earlier.

The minimal aggregate observer plus client state is useful for Inspect, but does not fully meet the clarified requirement for IFEval/DRACO. Before implementation, design an earlier canonical case-finalization boundary for boards with per-case evidence, shared with final aggregation. Validate the candidate outcome and all grading evidence there exactly once. Preserve failure handling, corrective-attempt selection, private grading material, accounting and final-report semantics. Do not score arbitrary intermediate checker calls or infer grades from 'Graded' activity text.

This earlier boundary is a broader refactor than adding a Log hook and may conflict with OME-932's original no-expression-change constraint. Determine whether existing per-case endpoints can host it without changing envelopes/expressions; if not, explicitly revise scope before implementation. No claim that one existing hook already solves early progress across all boards.

## Seam assessment

Source inspection identifies a plausible shared execution seam, not a ready-made progress hook:

- `benchmarks/protocol.py:preserve_candidate_outcome` invokes `/benchmarks/case-execution` after candidate invocation and protected grading complete. This is later and more complete than the board-specific envelope packers.
- `benchmarks/case_execution.py:CaseExecutionOutcome` combines case identity, candidate outcome, opaque grading evidence or grading failure. The route deliberately does not interpret benchmark evidence. It has no benchmark/scorer/material binding.
- `ScoredPath._case_result` already owns the canonical failure ladder and board grade hook. Its current interface depends on selected case metadata, RowIndex and private material. It is not yet independently callable using only CaseExecutionOutcome.

Recommended design direction: expose a single-case grading interface from the shared scored-path module, backed by the existing board adapter and canonical decoding/failure logic. Bind board identity, selection and material explicitly in execution composition. Where evidence is complete per case, execution can invoke this interface earlier; final aggregation must consume/reuse its typed result. Inspect may continue producing the same typed result during its existing async judge phase. A separate observer receives completed typed results and publishes cumulative scores. Core must never import the Inspect plugin or branch on benchmark names.

Do not place grading or judge calls in an observer: disabling progress must never change when or whether grading executes. A run-local result cache used only when observation is enabled is therefore not an acceptable shortcut. A durable typed result in the execution path is preferable, but changing the current envelope is a contract migration and must be evaluated against the ticket's constraints. A hidden cache also requires explicit cache-hit/replay/nested-run behavior and is not assumed simpler.

Outstanding proof obligations before calling this design clean:

1. Explicit benchmark binding without ambiguous ambient discovery for execution (observation discovery may safely decline; required grading may not).
2. One-case validation preserves authoritative selected position and anonymous error attribution currently handled by RowReader's whole-array indexing.
3. Reuse of the typed grade in final aggregation without repeated checks, judge calls or changed accounting.
4. Failure before case-execution still becomes exactly one final failed case; no fabricated early success.
5. Cached case execution and replay deliver final results correctly even when no live callback ran.
6. Compatibility with corrective attempts and all current board adapters.

Assessment: architecturally feasible, but a medium shared grading refactor rather than a small logging change. Existing source supports a candidate seam; executable parity tests are still needed. No URL4 language change is indicated. The earlier assertion that all 32 boards can be guaranteed now was too strong: common ScoredPath usage establishes leverage, not completed compatibility proof.

## IFEval proof result

The test-only incremental execution uses the real IFEval check and case-evaluation node routes, the extracted canonical `scored_path(specs)` factory, and the unchanged finalizer. While candidate 2 is explicitly blocked, candidate 1's grade and provisional headline score are available. Both a passing and failing instruction response match the complete batch payload after finalization. Counters show exactly one checker and one grade-hook call per case on the incremental path.

This proves reuse and timing under explicit early execution wiring. It does not prove production graph integration, cached grade transport, anonymous failure handling across singleton selections, or full-registry support. The shipped expression remains unchanged. Production integration still needs an explicit way to carry the typed grade into aggregation; the test's in-memory results list is not a proposed hidden run cache.

## Approved production IFEval slice

IFEval now carries a versioned, benchmark-bound canonical CaseResult from each iteration into aggregation. The new case-result endpoint reads the authoritative instruction for that case and uses the same scored-path adapter; final aggregation validates ordered case identity, inputs, metadata and revision, then finalizes the carried grades without regrading. Collected execution failures retain their selected position. A malformed grading result remains a run-level contract error despite iteration error collection.

This intentionally changes the IFEval protocol revision and expression. URL4 syntax/SDK and the public CandidateResult shape are unchanged. The original 50-case replay preserved score 0.9184, all case statuses, failures and coverage before its fingerprint/revision were migrated. Real production-expression tests establish early availability and full batch-payload parity. No callback-owned cache is introduced.

This slice does not yet publish provisional score events, change the Client table, or move other benchmarks' grading earlier. Those remain follow-up work; the original test-only proof above describes the preceding slice.

## Approved live IFEval preview

After each production IFEval grade, dispatch an optional observation fact with explicit benchmark/revision and canonical scorer. The enabled activity adapter maintains per-run, per-benchmark result state for cumulative scalar snapshots. It never regrades or owns the authoritative result. Repeated case facts replace by identity without double counting; rapid updates may coalesce, and the final CandidateResult remains authoritative. No arbitrary score inference in the Client. Initial rollout is explicitly IFEval; other boards need their corresponding production callback integration and acceptance tests.

Snapshot attributes: `sf.progress.schema=screamingface.benchmark-progress.v1`, `sf.progress.benchmark`, `sf.progress.benchmark_revision`, `sf.progress.revision`, `sf.progress.completed`, `sf.progress.graded`, and nullable finite `sf.progress.score`. The Client presents score zero correctly, rejects malformed/out-of-order snapshots, and marks partial scores Provisional. Active case numbering stays independent.

## Approved all-board extension
The user approved extending live score updates to all benchmarks. Publish canonical grade completion through the shared scored path for aggregate-time judges. Built-in early grading must carry the same typed result into final aggregation rather than grade twice. Preserve each board's scorer (including ContractEval confusion-matrix F1), failure mappings and metadata. This requires explicit built-in protocol/fixture migrations. The Client remains generic and shows only the running numeric score, without provisional text.

### Reviewed failure metadata correction
Typed grade validation must accept canonical grading failures that retain selected-case metadata without optional grading enrichment. Board-added metadata remains required for scored results; any supplied enrichment must match authoritative values even on failures. Identity, revision, input, and failure attribution checks remain strict.

### IFEval consolidation
IFEval must bind its existing canonical ScoredPath and native scorer into the shared Scoring transport. Preserve installed case order, anonymous error positions, no-regrading and corrupt-envelope rejection. Runtime uses shared endpoint adapters; the user approved migration of the endpoint intent to selected index/count and its fixtures.

### Direct endpoint bounds and terminal failures
Early-grade routes validate selected count against board availability before invoking loaders. Canonical failures first resolved during aggregation publish completion through the deduplicated progress observer. Failure completion is not dropped by fast-score coalescing; it must not create a numeric score for ungradeable cases.
