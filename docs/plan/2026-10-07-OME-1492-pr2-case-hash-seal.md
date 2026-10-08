# Plan — a broken seal says whether only the order moved (OME-1492 PR 2)

Spec: `docs/spec/2026-10-07-OME-1492-pr2-case-hash-seal.md` · ledger:
`docs/work/2026-10-07-case-hash-seal.md` · stacked on PR 1 (#1268) · landing: the Engine's inspect
plugin. Nothing paid runs; the backfill downloads datasets only (no model, no Judge).

Revised 2026-10-07: the first draft stored a per-Case fingerprint list; the backfill showed 3.3 MB
and two files over the 500 KB hook, and the owner chose one order-blind digest per declaration.

## Steps

Each line: step → verify.

1. **RED/GREEN — `case_set.py`** (`case_set_digest`, `what_moved`) with `test_case_set.py`:
   a reorder keeps it, a rewrite changes it, the two reasons, no Case text, rows without it add
   nothing. → verify: green.
2. **RED/GREEN — Case Preparation** appends `what_moved` on a Case Digest mismatch (append to
   `test_task_replay.py`: reordered stand-in Hub eval, rewritten text, row without the field).
3. **RED/GREEN — the importer** seals `case_set_digest` from run 1 and the row writer writes it
   (append to `test_import_replay.py` and `test_task_replay_rows.py`).
4. **Backfill** (one-off scratch script, not committed): replay all 57 declarations; insert a value
   only where the Case Digest still matches; verify each declaration's value equals its replay's.
5. **Gates**: `run_gates.py screamingface-engine --base <PR 1 tip>`, no skip flag; extra-less
   pyright on the touched files.
6. **Docs in the PR**: ledger outcome; one dated line in the OME-1492 mirror.
