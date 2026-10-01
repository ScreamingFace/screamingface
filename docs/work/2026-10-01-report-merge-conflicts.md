---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Report merge conflicts — integrate current main

## Intent

Resolve draft PR #1156 against current main while preserving upstream behavior and bounded, durable report recovery.

## Planned changes

- Merge origin/main into OME-1422-report-pagination; resolve overlapping SDK changes and regenerate the dependency lock if necessary.

## Test plan

- Inspect both commits behind each conflict and preserve their existing behavioral tests.
- Run the complete SDK gates and check the updated PR's mergeability and CI.

## Acceptance

- No conflict markers remain; upstream features and report recovery tests pass; draft PR is updated without merging it into main.

## Outcome

- **Actual files:** resolved `_core/ports.py` by retaining both result_path and cache_hits; resolved `_ui/report_view.py` by retaining the inverted-grade line and optional download control. Added `test_report_merge_compatibility.py` to verify cached outcome persistence, inverted-grade recovery and streamed exports, and the single live Download action.
- **Commits:** merge origin/main at ba1545d8 into the draft branch; no upstream history rewritten.
- **Gates:** all screamingface gates green: Ruff, formatting, Pyright, full parallel pytest with the unchanged 95% coverage floor, notebooks, build and distribution. Focused recovery/compatibility tests: 24 passed.
- **Deviations:** upstream introduced parallel pytest. The first parallel run reproduced differing collection names caused by os.getpid() in an existing parameterization. Added explicit stable IDs only; parameters, function body and assertions are unchanged. Both parents' existing tests were preserved by automatic merge. The append-only baseline is the inspected merged contract tree 8a6c6006659d79d477e6720a592b2a86391dece4, since either parent alone flags the other parent's already committed test changes.
- **Wisdom review:** preserves both upstream meanings without duplicate UI actions or new production abstractions. Recovery retains the new fields; no schema, authentication or retention behavior changed by conflict resolution.
