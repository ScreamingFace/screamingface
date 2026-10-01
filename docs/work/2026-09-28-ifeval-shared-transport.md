---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# IFEval shared transport

## Intent
Use the same canonical early-grade binding, endpoint adapters and final typed-result reduction for IFEval as other built-ins. Retain IFEval checker, scorer, installed case order and failure rules.

## Planned changes
Add a board-owned Scoring factory, remove duplicated incremental orchestration, and wire runtime/protocol to shared adapters. Migrate expression pins and replay after user approval.

## Test plan
New real-fixture round-trip parity and no-regrading tests; preserve existing production timing/checker-count/failure assertions; cache-only IFEval replay; full Engine and Client gates.

## Acceptance
One transport implementation serves all built-ins; IFEval output/scoring and one-grade-per-case behavior unchanged.

## Outcome
- User approved fixture migration and public single-case cleanup.
- Removed IFEval's duplicated transport module; its 20-line binding supplies canonical hooks to shared adapters. The protocol now supplies selected index/count through `early_result`.
- Public `ScoredPath.case_result` serves batch iteration and early transport; no private-method access remains between them.
- New tests first failed for absent shared binding/public method, then passed. 24 focused tests pass, including real generated protocols, no-regrading, installed-order and failure parity.
- Cache-only 50-case IFEval replay retained score 0.9184 and identical statuses/failures/coverage; only revision and expression SHA migrated.
- Wisdom: transport has one implementation, checker/scorer unchanged, no compatibility fallback or extra model calls. Full Engine and Client gates green, including coverage, layering, notebooks, build and distribution.

- Commit: `refactor: consolidate IFEval grade transport`. No additional scope or paid calls.
