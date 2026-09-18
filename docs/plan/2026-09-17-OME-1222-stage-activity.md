# OME-1222 revised implementation plan

1. Add RED tests calling shared endpoint factories directly under an observer and log sink, plus async decorator failure/parentage coverage.
2. Expose one observe_stage decorator backed by the existing optional observer and fault guard; no stage_scope or reports_stage APIs. Document partial-entry cleanup and ignored suppression.
3. Move shared aggregation, case reduction, rubric checking and candidate answering emission into the implementations that own the work. Move remaining board-owned stage scopes into their actual producers; remove installation-time wrappers.
4. Keep URL4, grading hooks, route definitions, payloads, deployment policy and old tests unchanged. Run stage tests and full Engine gates; independent review.
5. Update justified PR/ticket descriptions, push to the existing draft. Keep Linear In Progress.

Owner-approved consolidation: one plugin-independent ActivityKind, four stages plus model-call detail, no grading subkinds or BenchmarkStage duplicate. Mechanically migrate the inherited refusal-validation test with the approved append-only exception; run all other gates.

## Case attribution wiring — 2026-09-18
Add stage/candidate attribution regressions first; include safe current case facts in ActivityObserver.stage and move candidate stage observation around the scoped evaluation method. Verify interleaving and exact input preservation. Audit graph-owned grading and role metadata separately before changing generated expressions.

## Remaining attribution implementation order

1. Confirm explicit Client compiler metadata scope in #983 (question pending), while keeping Engine producer changes in #980. Use OME-699 as the existing semantic-attribution design authority; do not duplicate its ownership contract.
2. Define selection metadata at the shared benchmark protocol boundary, preserving selected order and original input payloads. Test arbitrary/leading-zero IDs, sliced/subset selections and concurrency before changing builders.
3. Define a real grading execution boundary that encloses directly dispatched judge calls and terminal case reduction. Audit deterministic IFEval, rubric fan-out, DRACO passes, MedXpert turns and imported Inspect boards. Do not label an endpoint return as whole-case completion.
4. Pass explicit operation roles from authored calls; test the same provider/model used as both member and synthesiser. Keep unknowns absent. Observation removal must preserve provider requests.
5. Wire Client fields/wording in #983 and run full/off fake-provider parity, Client replay fixtures through the approved migration procedure, and all gates. No real model calls for validation.

The exact transport for scoped grading metadata remains a design item: static query metadata cannot carry dynamic Case references. Do not implement a route-name heuristic or re-evaluate an already-resolved response as an executable recipe.


## Scope correction — selected-case numbering only

Owner deferred model-role attribution and whole-case grading boundaries. The earlier compiler question is superseded; do not implement that expansion. #988 now owns selected-case position/count in the candidate envelope and scope. #980 forwards the validated pair on model and scoped stage activity; #983 renders it. Preserve existing privacy/off behavior, parentage and all four stages. Add pair-validation and native event tests, then run full Engine gates.
