---
ticket: OME-1222
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1222 — Benchmark stage activity

## Intent
Expose work between model calls through the existing ephemeral activity stream. Owner requested a draft Engine PR; the approved OME-887 stage vocabulary and OME-1161 plugin provide the contract and infrastructure.

## Planned changes
- Benchmark-owned optional observation port and typed handler wrapper; explicit stage declarations in shipped runtime installers and candidate adapter.
- Small generic access/guard extension to observations; activity implements the benchmark port, retaining run policy and heartbeat ownership.
- New regression tests and spec/plan/task artifacts. No Client or URL4 changes.

## Test plan
RED tests for stage lifecycle, sync/async shape, failure isolation, cancellation, off/nested runs, node attachment, concurrent attribution and installer coverage. Existing Engine suite remains unchanged.

## Acceptance
All six stage kinds have explicit owners, optional observers cannot change execution, private payloads stay out of attributes, and full Engine gates pass. Open a draft against main; no deployment or paid provider calls.

## Outcome
- **Actual files:** benchmark stage port; explicit wrappers in five built-in runtime families, imported single-shot runtime and candidate adapter; activity adapter; 12 generic observation access/guard lines; three new test modules; spec/plan/task artifacts.
- **Commits:** recorded by this PR's feature commit (Refs: OME-1222).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN (append-only, Ruff check/format, Pyright, layering, full pytest/coverage). Coverage report rounds to 94%. 33 new parametrized regression cases.
- **RED evidence:** missing stage module; eight missing-registration/node-log regressions; both sync/async cleanup-interruption cases failed before their fixes. Healthy full/off one-case runs pass on all seven built-in boards with byte-equivalent decoded full results and identical provider requests.
- **Review:** independent Standards and Spec reviews clear after fixing multi-observer cleanup and adding successful-board parity. Existing tests unchanged.
- **Wisdom:** explicit owner declarations avoid route inference; the optional domain port keeps plugin imports out of core. No payload data crosses the port, no new dependency or storage, no scoring changes. Existing fault guard and timer cleanup are reused.
- **Deviations:** minimal generic registry access/guard required because merged ports cover only model calls; execution core remains benchmark/activity-agnostic. New scope unwinding handles cancellation across multiple observers. Imported adapter installation tested without optional scorer packages; not a production-load or widget test.
- **Delivery:** draft PR against main; implementation complete, ticket remains In Progress while draft, then In Review when marked ready.

Owner correction, 17 September: draft PRs remain In Progress in Linear; corrected the issue and task mirror.

## Revision — endpoint-owned activity (owner approved)

Intent: keep URL4 unchanged; registration is routing, not progress ownership. Shared benchmark endpoint factories own semantic stage scopes; board-specific producers scope their own work. Preserve existing stage contract, grading results, privacy and cancellation.

Plan: introduce a dual sync/async `stage_scope` using the existing optional benchmark observation port; move aggregation and case reduction into shared evaluation factories, rubric check into its shared factory, and answering into the candidate handler. Move remaining board-specific scopes into producers and remove installer wrappers. No grading-hook signature changes, no payload logging, no route parsing. Existing generic DAG lifecycle remains unchanged.

Tests: direct invocation of shared factories must emit exactly one semantic lifecycle under the existing log sink; scope around awaited work must retain parentage and original failures. Existing installation and board parity tests stay unchanged. Full Engine gates and review before push.

Status: IN_PROGRESS. No URL4 capability is being implemented.

Revision outcome: shared evaluation factories, shared rubric checker and candidate handler own their emission via `reports_stage`; local board-specific producers declare only their own stage. All endpoint installers restored to the main-branch implementation. `stage_scope` supports explicit awaited regions; the convenience decorator is deliberately limited to native sync/async functions. StageScope now specifies partial-start cleanup and ignored suppression. No URL4 changes.

RED: three direct shared-factory tests emitted no records; explicit scope test failed because stage_scope was absent. GREEN: 37 focused cases pass, including existing installation and all-board full/off parity. Full local Engine gates ALL GREEN (append-only, lint, format, types, layering, full pytest/coverage). Existing tests unchanged. Independent Standards and Spec re-review found no substantiated issues; the spec reviewer independently reran all 37 cases.

Wisdom: shared-factory ownership removes repeated installer decoration without route inference or a new SDK capability. Individual board changes are small declarations, not a copied progress pipeline. A broader generic lifecycle dispatcher refactor is unnecessary for this unit. No invented progress counters or grading changes. Revision complete; retain draft PR and In Progress ticket.

## Revision — one decorator API (owner requested)

Intent: remove stage_scope entirely, rename reports_stage to observe_stage, retain only the internal lifecycle dispatcher. Fixed BenchmarkStage vocabulary; no custom-stage registration. Owner explicitly requested API removal and consolidation, so migrate the affected tests to the new decorator spelling while preserving their behavioral assertions and async parentage/failure coverage. No production block-scope caller exists.

Plan/test: add RED coverage for decorator syntax, simplify API and migrate callers/tests, run all stage tests and full Engine gates. Keep PR draft and ticket In Progress. Existing two-argument helper is replaced, not retained as a compatibility API for this unmerged feature.

Decorator revision outcome: stage_scope and reports_stage removed from all production/test code; observe_stage(stage) is the sole decorator API. Native sync/async execution uses the same internal _StageCall, with no new lifecycle behavior. RED decorator test failed with missing handler argument; all 38 focused cases now pass. Full local Engine gates ALL GREEN. Prior PR tests migrated mechanically for the owner-requested removal; their failure, cancellation, privacy and parentage assertions remain. Tests inherited from main remain unchanged. Wisdom review: fixed vocabulary, smaller API, no speculative block capability or URL4 change. Keep draft/In Progress.

## Revision — four researcher-facing stage labels

Owner selected exactly Loading cases / Answering / Grading / Aggregating. Map the fixed producer kinds to these message labels; preserve the structured v1 kinds so all grading substeps remain diagnostic details, and model_call remains a detail rather than a fifth stage. Add label mapping tests before implementation. Document the four-category projection for the future Client. No Client code or wire schema change.

Label revision outcome: messages use the four approved labels; structured producer kinds and model-call detail remain unchanged. Five RED mapping cases now pass; all 45 focused tests and full local Engine gates pass. No frontend implementation claimed. Existing tests unchanged. Keep draft/In Progress.

## Revision — four actual stages and one vocabulary

Owner requires four real stages, not just display labels, and approved removing duplicate BenchmarkStage/ActivityKind definitions. Plan: define one plugin-independent ActivityKind (case_loading, answering, grading, aggregation, plus model_call detail); benchmark decorators and activity adapter use the same enum directly. Keep diagnostic occurrences/parents/timing and existing privacy/admission. Document compact/detailed client display without implementing Client work. Grading subkind wire values are intentionally removed; no compatibility aliases.

Testing: exact shared-vocabulary regression, four stage producer tests, original request/result parity. One test inherited from main references GRADING_CHECK solely to reject refused state; requested owner confirmation for its mechanical migration and append-only exception before editing it. No assertion weakening. All other gates remain required.

Consolidation outcome: single ActivityKind in plugin-independent activity_kinds.py; four real stages plus model_call detail. Removed BenchmarkStage and all three grading subkind members/usages from production and tests. Observer passes the same enum directly, without string conversion. Benchmark decorator rejects model_call. Structured operation IDs, timing, state and parents remain intact; labels stay the approved four. Canonical activity spec updated for the intentional vocabulary change.

Validation: RED missing shared-vocabulary module; 74 targeted tests pass (43 feature cases plus existing activity contract tests). Full Engine lint, format, typing, layering and pytest/coverage gates ALL GREEN. Owner approved migrating the existing refusal-rejection test from GRADING_CHECK to GRADING and the append-only exception; assertion unchanged. Use the same narrowly approved append-only exception in the Engine pre-push gate, retaining all other gates and normal commit hooks. Self-review: one enum, no aliases/new stage registry, no Client implementation or transport/schema-field changes, no grading result changes. Keep draft/In Progress.

## Stack on case attribution — 2026-09-18
Owner authorized stacking #980 on draft #988 so Client work can proceed against the combined Engine. Rebased onto dd367d4b; resolved only overlapping imports and the identical active-observation accessor. Preserve case envelopes/model attribution and four-stage lifecycle behavior. No new stage-attribution API in this mechanical stack. Validate the combined Engine gates before a lease-protected push; keep draft/In Progress and merge #988 first.

Stack validation: full Engine gates with the optional Inspect extra installed pass (Ruff, formatting, Pyright, layering, full tests/coverage). Range-diff confirms conflict resolutions preserve both features; the active-observation accessor now comes from #988. No Client or stage-case attribution behavior added in this rebase.

## Case attribution wiring — 2026-09-18
Owner approved real attribution wiring. First move Answering observation inside the existing decoded case scope and include safe case facts on stage records. Validate concurrent cases, nested grading and unsafe IDs before broadening the attribution contract. Direct graph judge calls and synthesis roles require explicit request metadata; do not infer either from route names or report fingerprints.

Wiring validation: 37 focused stage/case tests passed; all Engine gates passed (lint, format, types, layering and full coverage suite). New tests failed first on missing stage case_id, then passed after moving observation inside the decoded scope. Prior tests unchanged. Self-review: shared safe-fact validation, unchanged prompts/results, no core/plugin dependency inversion, no URL4 or generated-expression changes. Scope limitation: direct graph grading calls and selected-case ordinals are not newly attributed by this patch.

## Remaining attribution investigation — 2026-09-18
Owner explicitly placed remaining Engine work in #980. Rechecked model dispatch, benchmark protocol, corrective adapters and retained operation attribution. Confirmed that exact live model roles require explicit authoring metadata, dynamic Case fields cannot be interpolated through query params, and direct judge calls sit outside verdict-handler observation. Updated spec/plan with concrete boundaries and required parity checks before broadening implementation. Asked whether the companion compiler production belongs in #983; that dependent scope remains pending. No production changes made in this investigation.


## Scope correction — selected-case numbering only

Owner deferred model-role attribution and whole-case grading boundaries. The earlier compiler question is superseded; do not implement that expansion. #988 now owns selected-case position/count in the candidate envelope and scope. #980 forwards the validated pair on model and scoped stage activity; #983 renders it. Preserve existing privacy/off behavior, parentage and all four stages. Add pair-validation and native event tests, then run full Engine gates.

Numbering progress: model start/retry/completion and scoped stage producer tests pass (3 cases, including disabled mode). The parent #988 case_context.py change is temporarily copied into this worktree for these tests and the native notebook preview; remove that duplicate diff before rebasing onto the eventual #988 commit. No new #980 commit/push. Full integration waits for parent test-migration approval and gates. Client consumer pushed as a2712060 with all Client gates green. Case-numbering-preview.ipynb executes native producers with simulated work, zero invalid records; no paid calls or local Engine restart.

Selected-case numbering completed: rebased on #988 commit 69db8df4, removed the temporary duplicate parent file, and resolved the candidate-handler overlap by entering the numbered case scope before the observed Answering method. New producer tests cover enabled/off mode, retry and completion, stage/child agreement. All Engine gates green, including append-only. Real local HTTP/URL4 two-case IFEval execution delivered (1,2) and (2,2) on Answering records to the Client with zero invalid records; no model requests. Runtime restarted from this checkout successfully.

Wisdom review: only plugin serialization reads the benchmark-owned scoped facts; no core/plugin inversion, identity inference, new index or role taxonomy. Direct graph grading outside the case scope remains unattributed. Issue and PR stay In Progress/draft. Commit: feat(engine): publish selected-case positions in activity (Refs: OME-1222).


## Whole-case grading activity — 2026-09-18
Owner resumed this scope: one numbered Grading operation must enclose the complete grading graph, including judge calls and case reduction. Implement a shared benchmark-owned grade-case adapter invoked by preserve_candidate_outcome. Carry explicit case identity/selection metadata and required lexical bindings outside grading input; evaluate the authored grading expression in its singleton case iteration. Preserve the existing outer error-collection boundary and candidate outcome. Decorate the scoped adapter evaluation with observe_stage(GRADING); detailed endpoint events remain explicitly parented. Client may hide successful nested grading scopes under this real parent, never merge adjacent records. No URL4/core execution changes. Test native context/parentage, success/error/cancellation and disabled parity; migrate generated-expression fixtures only after replay equivalence is established. Keep #980 draft and stacked on #988.

Prototype outcome: REJECTED, no production change retained. Moving the grading Node into a request intent caused premature lexical/item substitution (including rubric rows and MedXpert reasoning). Existing failure-integrity and two-turn tests exposed changed grading outcomes. A standalone public node.evaluate env does not bind URL4's reserved iteration item. Do not ship an encoded-expression workaround or weaken parity tests for logging. Before implementation, design a grading boundary that preserves the original lexical execution scope, with a separate explicit decision about generated-protocol changes. Prototype files/evidence remain under ignored .docs/OME-1222 and /tmp/grading-parity*.log. Client 3025ebb1 is complete and independently green.


## Approved discrete case-grading signals — supersedes execution wrapper
Owner approved keeping benchmark execution unchanged. Emit a started fact after the authoritative checker/task preparer decodes its case ID, and completed/failed from the existing case-execution envelope after outcome construction. A benchmark-owned optional observation port forwards only case ID and state; the activity plugin owns wire records/admission. Case-phase records use scope=case and a deterministic run-local case ID, start revision 1 and terminal revision 2; the Client does not reopen a completed phase on a late start. They carry no measured duration or heartbeat claim. No new timers. The activity adapter tracks at most 1,024 pending case identities, releases each at completion and clears all on run cleanup; terminal signals without a matching start are ignored. Imported Inspect boards emit around their actual scorer during aggregation, not answer recording. Checks inside candidate execution do not emit benchmark case phases. Duplicate active starts are ignored, and the Client rejects late start revisions after a terminal record. Off mode stays inert. Client joins position/count only by explicit candidate/run/case ID already received from answering, retaining ID-only fallback. Render one case phase, hide routine lower-level grading rows while preserving failures/model calls and raw bounded history. No URL4 expression changes or golden migrations. Validate all shipped grading entry points, failure envelopes, observer faults/off, out-of-order terminal records and Client isolation/numbering.

Case-phase validation: full Engine gates passed (lint, format, types, dependency layering and all tests/coverage). Seven focused signal tests passed with the Inspect extra, including actual match scorer, pending bound/cleanup, observer failure, disabled mode and candidate-check exclusion. Real HTTP/URL4 two-case IFEval with literal answers emitted both numbered case-phase outcomes through the Client, with zero invalid records. Existing expressions and golden fixtures are unchanged. Draft/In Progress retained.


## Updated benchmark integration — 2026-09-22
Owner approved updating draft #980 on #988. Integrate the updated base while retaining the stack; preserve main's error classification and shared serving spine. Move loading observation to the shared serving handler, preserve MedXpertQA grading signals, and add ContractEval grading observation. Validate actual lifecycle emission and full/off outcome parity, then full Engine gates; keep draft/In Progress.

Outcome: integrated #988 at ec6366c3, resolving six conflicts while preserving main's failure classes and shared serving implementation. Existing installation tests first failed for MedXpertQA and ContractEval loading; both pass after observing `serve_cases` once. ContractEval now observes its checker and signals the decoded Case ID. All eight built-in boards pass full/off parity with identical requests and full result JSON. The owner approved additive ContractEval assets and Inspect test setup migration. The scorer test now lives under tests/unit/inspect so the extra-enabled CI lane executes it; its scoring/activity assertions remain. All 25 focused checks and all Engine gates pass, with the approved append-only migration exception. Independent Standards/Spec integration reviews report no actionable issues. No generated-expression, scoring or prompt changes. PR/Linear descriptions refreshed; remain draft/In Progress.


## Imported scorer thread context — 2026-09-23
Owner reported that real aggregation loses grading facts at the worker-thread boundary. Reproduce via imported GSM8K's actual aggregation route and native log sink, then carry a fresh copied context into the worker. Preserve scores and run isolation, test enabled/disabled operation, and run Engine gates. Keep draft.

Diagnosis: actual imported aggregation uses spine/scored._run_sync, not the check-surface helper. Copying context there preserves the observation owner but still yields zero logs: URL4's native LogSink rejects off-thread emission by contract. The copy-only attempt was removed. The new full-route test is RED (score 0.5, zero expected case facts); disabled mode passes. Proposed async aggregation entry point keeps scoring on the native endpoint loop while preserving the synchronous API. Awaiting owner decision before that API change.

### Async correction approved
User approved starting with #980 async fix. Implement the additive async path described in the spec/plan; preserve all existing tests and synchronous APIs. RED real-route regression already demonstrates missing case events despite correct score. Acceptance requires real-route events plus unchanged report payloads, validation and cancellation.

Owner approved updating the existing imported installation test to await async handlers, preserving its error and stage assertions. Full prior run: 3,593 passed, one outdated synchronous test invocation failed; coverage 94.16%. Rerun with the approved append-only exception.

Async correction outcome: full Engine gates GREEN (lint, format, types, layering, full tests/coverage), with owner-approved existing-test migration exception. 174 focused async/Inspect tests passed, including actual GSM8K route logs, full report parity and cancellation cleanup. Independent Spec and Standards reviews found no actionable findings. Changes are limited to shared async aggregation adapters and imported-board wiring; no URL4 or Client change. Integrates latest #988 base d22cec0e. PR remains draft/In Progress. Pre-push uses the unchanged stack gate selection with the same explicitly approved --skip-append-only exception; no behavioral gate is skipped.
