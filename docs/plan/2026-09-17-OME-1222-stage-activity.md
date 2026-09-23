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


## Whole-case grading activity — 2026-09-18
Owner resumed this scope: one numbered Grading operation must enclose the complete grading graph, including judge calls and case reduction. Implement a shared benchmark-owned grade-case adapter invoked by preserve_candidate_outcome. Carry explicit case identity/selection metadata and required lexical bindings outside grading input; evaluate the authored grading expression in its singleton case iteration. Preserve the existing outer error-collection boundary and candidate outcome. Decorate the scoped adapter evaluation with observe_stage(GRADING); detailed endpoint events remain explicitly parented. Client may hide successful nested grading scopes under this real parent, never merge adjacent records. No URL4/core execution changes. Test native context/parentage, success/error/cancellation and disabled parity; migrate generated-expression fixtures only after replay equivalence is established. Keep #980 draft and stacked on #988.

Prototype outcome: REJECTED, no production change retained. Moving the grading Node into a request intent caused premature lexical/item substitution (including rubric rows and MedXpert reasoning). Existing failure-integrity and two-turn tests exposed changed grading outcomes. A standalone public node.evaluate env does not bind URL4's reserved iteration item. Do not ship an encoded-expression workaround or weaken parity tests for logging. Before implementation, design a grading boundary that preserves the original lexical execution scope, with a separate explicit decision about generated-protocol changes. Prototype files/evidence remain under ignored .docs/OME-1222 and /tmp/grading-parity*.log. Client 3025ebb1 is complete and independently green.


## Approved discrete case-grading signals — supersedes execution wrapper
Owner approved keeping benchmark execution unchanged. Emit a started fact after the authoritative checker/task preparer decodes its case ID, and completed/failed from the existing case-execution envelope after outcome construction. A benchmark-owned optional observation port forwards only case ID and state; the activity plugin owns wire records/admission. Case-phase records use scope=case and a deterministic run-local case ID, start revision 1 and terminal revision 2; the Client does not reopen a completed phase on a late start. They carry no measured duration or heartbeat claim. No new timers. The activity adapter tracks at most 1,024 pending case identities, releases each at completion and clears all on run cleanup; terminal signals without a matching start are ignored. Imported Inspect boards emit around their actual scorer during aggregation, not answer recording. Checks inside candidate execution do not emit benchmark case phases. Duplicate active starts are ignored, and the Client rejects late start revisions after a terminal record. Off mode stays inert. Client joins position/count only by explicit candidate/run/case ID already received from answering, retaining ID-only fallback. Render one case phase, hide routine lower-level grading rows while preserving failures/model calls and raw bounded history. No URL4 expression changes or golden migrations. Validate all shipped grading entry points, failure envelopes, observer faults/off, out-of-order terminal records and Client isolation/numbering.


## Updated-base integration — 2026-09-22
Preserve the shared serving spine and error classes from #988/main. Move MedXpertQA's former loader declaration into `serve_cases`, add ContractEval checker stage and case-start declarations, and extend the existing all-board parity fixture with ContractEval assets. Validate shared loading once, grading entry signals, eight-board full/off parity, real optional Inspect scoring, and the complete Engine gates. Keep #980 draft and stacked on #988.
