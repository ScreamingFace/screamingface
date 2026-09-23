---
ticket: OME-1222
stack: screamingface-engine
status: in_progress
started: 2026-09-23
finished: 2026-09-23
---
# Stage activity on native case indexing

## Intent and plan

Restack #980 on updated #988 after native `$index` integration. Preserve producer-owned
stage instrumentation, per-case activity and asynchronous Inspect scoring. Resolve cases
loader conflicts by retaining the new validated registration and existing observation.
No new event kinds or UI changes.

## Tests and acceptance

Full Engine gates including Inspect; Client decoding and local two-case IFEval activity
smoke. Keep case_position/case_count event shape and four stages; unchanged grading results.
Owner approved necessary obsolete-test migration in this follow-up. Push with lease,
keep #980 draft/In Progress; do not merge.

## Outcome

Restacked on #988 at 4895014e, preserving the producer decorators, shared serving
integration, ContractEval coverage and async Inspect aggregation from previous #980.
Existing stage-installation coverage now checks the cases processor; its imported board
fixture declares the new required difficulty field. No behavioral assertions removed.

Full Engine gates with Inspect pass (lint, format, types, layering, full pytest/coverage).
Compared the final production diff with prior #980: only native-index/base changes remain;
async grading and case phases are preserved. A real HTTP/URL4 two-case IFEval smoke through
the updated local stack decoded all four stages with zero invalid events, and positions
(1,2), (2,2). Literal answers avoid paid model requests. Local preview runs #980 sources
with full activity enabled. #988 independently passed full Client gates and all 382
cached replay cases. PR remains draft / issue In Progress pending merge.

The older #980 integration commits were merges; rebase omits their merge resolutions.
Restored those reviewed resolutions explicitly and verified them against the previous head.
