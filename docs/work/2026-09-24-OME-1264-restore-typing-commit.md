---
ticket: OME-1264
stack: screamingface-engine
status: done
started: 2026-09-24
finished: 2026-09-24
---

# OME-1264 — Restore the clobbered data_files typing commit

## Intent

Second recovery from the stack-rebase force-push (same incident as PR #1046):
a peer session's `9897359b` — narrowing `data_files` from `Any` to
`dict[str, str] | None` (TaskFacts, SnapshotSpec, `_conserved_data_files`
return) and correcting a test docstring that still claimed the bare-str shape
is conserved — sat on the pre-rebase #1033 tip and never merged. The redundant
sibling (`748f3512`, a ledger flip already done by #1044) is dropped.

## Outcome

- **Commits:** cherry-pick of `9897359b` (peer authorship preserved).
- **Gates:** run recorded in the PR; inspect lane + full gates.
- **Deviations:** none.
