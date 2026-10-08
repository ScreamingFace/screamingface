---
ticket: unfiled
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# Streamed atomic report export — merge current main and review

## Intent

Resolve PR #1241 against main `21132c8d006e0315305149ddb3ebead07904bda9`
while preserving streamed byte-compatible report exports, atomic failure retention,
and every inherited assertion. Review the combined PR before pushing its branch.

## Planned changes

- Merge the pinned main revision into `OME-1486-streamed-atomic-report-export`.
- Resolve overlapping hunks according to original commit intent; record actual files.
- Add regression tests first if review reveals a behavior defect needing correction.

## Test plan

- Capture the conflict signal, inspect base/ours/theirs and source commit intent.
- Run focused streamed-export and atomic-file regressions, including exact bytes,
  permissions/symlinks, descriptor cleanup, long names, and failed-write retention.
- Independent Standards/Spec review against the merged main revision.
- All screamingface card gates: preserved tests, format/lint/types, full suite and
  95% coverage floor, notebook validation, builds/distribution.

## Acceptance

No unresolved hunks, both main and export intent retained, no weakened tests,
reviews complete, all gates green, finished merge commit pushed to PR #1241.

## Outcome

Resolved the single conflict in `packages/screamingface/src/screamingface/report.py`
by preserving main's named `scores` field alongside the export branch's lazy
`cases` iterator. No inherited tests or assertions were modified.

Focused export, atomic-file, Case-boundary, and named-score tests: 43 passed.
The initial sandbox run stripped a setuid fixture bit before implementation ran;
the same unchanged tests passed with the required filesystem permissions.
Independent Standards and Spec reviews found zero actionable findings; explicit
named-score JSON byte parity also passed.

All screamingface card gates passed against pinned main: append-only tests, Ruff
lint/format, Pyright, full pytest suite with the 95% coverage floor, notebook
validation, build, and distribution checks. No paid calls were made.

Confidence: 97%. The merge retains both source intents and is validated locally;
GitHub's remote mergeability and CI status are checked after pushing.

Wisdom: when a serializer refactor overlaps a new serialized field, preserve the
field in the shared export envelope and retain the lazy Case boundary.
