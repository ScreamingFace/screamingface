---
ticket: OME-1468
stack: repo
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1468-approvals-cover-python-and-json — Let blob-pinned owner approvals cover Python tests and JSON fixtures in the append-only gate

## Intent

`approved_test_changes.py` gives an owner-approved, blob-pinned test-contract change a pass through
`run_gates.py`'s append-only check, but only for TS/TSX. Python tests and JSON fixtures had no
approval path, so every approved change to them ran gates with `--skip-append-only` and pushed with
`--no-verify`, skipping the check for the whole stack. Extend the same fail-closed, byte-exact
mechanism to `.py` test files and JSON fixtures under `tests/`. The ticket (`OME-1468`) is the spec.

## Planned changes

- `.claude/scripts/approved_test_changes.py` — the blob-pair matcher factored out of the TS entry
  point; JSON fixtures under a `tests/` directory join the "no range parser" path; a new
  `approved_python_test_change` for `.py` files under `tests/`.
- `.claude/scripts/run_gates.py` — the Python AST range check consults the approval before it adds a
  modified file to the offenders. Nothing else in the append-only check changes.
- `.claude/scripts/tests/test_approved_py_json_change.py` — new.
- `docs/tasks/2026-10-02-OME-1468-approvals-cover-python-and-json.md` — mirror.

## Test plan

- An approved Python edit that breaks a protected range passes.
- The same file with one more byte changed fails.
- A wrong branch fails; a missing (and a blank) reason fails.
- An unapproved second Python file in the same diff still fails.
- A JSON fixture under `tests/` passes when approved, fails on an extra byte, a wrong branch, a
  missing reason; a JSON file outside `tests/` is never approvable.
- An approval whose entry lacks one of the two blobs fails.
- `test_approved_ts_change.py` and `test_run_gates.py` pass unchanged.

## Acceptance

- All of the above green, existing script tests green and unmodified.
- `run_gates.py aigateway` green with the append-only check on.
- Existing approval files (OME-939, OME-1134, OME-1250, OME-1322) validate on their branches.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `approved_test_changes.py` keeps `approved_unsupported_change`
  (TS/TSX unchanged, plus JSON under `tests/`) and adds `approved_python_test_change`; both share
  the blob-pair matcher `_approved_blob_transition`. `run_gates.py` consults the Python approval
  only after the range check has found a violation; an unparseable current file, deletes, renames
  and type changes still fail regardless.
- **Commits:** `feat(gates): let blob-pinned owner approvals cover Python tests and JSON fixtures`
  (sha in the PR and the Linear close comment).
- **Gates:** new suite 16/16 (review follow-up added two changed-baseline tests; mutating
  the `base_blob` comparison to `True` now fails both); `test_approved_ts_change.py`, `test_run_gates.py`,
  `test_pre_push.py`, `test_check_mirror_status.py` green and unmodified;
  `run_gates.py aigateway --base origin/main` → ALL GATES GREEN with the append-only check on.
  Existing approvals replayed on their branches with the new scripts: OME-939 (aigateway +
  screamingface-engine), OME-1134 (screamingface-engine), OME-1250 (screamingface, JSON) now
  pass where the old scripts failed; OME-1322 (aigateway-ui, TS) passes under both.
- **Deviations:** `.claude/scripts/tests` are not run by any CI workflow except
  `test_check_mirror_status.py`; they were run locally via `uv run <file>` per their docstrings.
  The OME-1134 manifest's stale `note` was updated (doc-only; blobs untouched) on review request.
