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
