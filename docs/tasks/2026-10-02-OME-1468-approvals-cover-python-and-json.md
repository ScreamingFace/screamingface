---
id: OME-1468
linear_url: https://linear.app/openmined/issue/OME-1468/let-blob-pinned-owner-approvals-cover-python-tests-and-json-fixtures
status: in_review
type: task
priority: high
labels: [repo-dev-processes, agentic]
created: 2026-10-02
---

# Let blob-pinned owner approvals cover Python tests and JSON fixtures in the append-only gate

`approved_test_changes.py` exempted only TS/TSX test edits that an owner approved and pinned to an
exact base→approved blob pair. Python tests and JSON fixtures had no such path, so approved changes
to them ran `run_gates.py --skip-append-only` and pushed with `--no-verify`, skipping the check for
the whole stack. This extends the same fail-closed, byte-exact approval to `.py` test files and
JSON fixtures under `tests/`. The Python AST range check consults the approval before failing a
modified file; the TS path is unchanged.

- 2026-10-02: work started on branch
  `bershadsky/ome-1468-let-blob-pinned-owner-approvals-cover-python-tests-and-json`, ledger
  `docs/work/2026-10-02-ome-1468-approvals-cover-python-and-json.md`.
- 2026-10-02: PR opened; moved to In Review.
