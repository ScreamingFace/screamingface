# OME-1709 — byte-exact approval of a `.js` test change, and run the approval tests

Status: draft for owner review (2026-10-21).

## Problem

The append-only check (`run_gates.py`) cannot parse `.js` tests, so a change to a prior portal
test under `apps/scoreboard/tests/portal/` is "unsupported or unparseable" and fails. The
byte-exact approval path (`.claude/scripts/approved_test_changes.py`,
`approved_unsupported_change`) covers TS/TSX tests and JSON fixtures, not `.js`. An owner-approved
portal-test change therefore needs `--skip-append-only` and `git push --no-verify`, which turn off
the whole check for the stack and the whole pre-push hook (OME-1460, OME-1596, now OME-1655).

The two existing approval test files (`test_approved_ts_change.py`, `test_approved_py_json_change.py`)
are run by no gate and no CI job.

## Change

1. `approved_unsupported_change` also accepts a `.js` file **under a `tests/` directory**
   (`_under_tests`, the same rule JSON fixtures use). It is narrower than TS/TSX on purpose: a
   served portal file such as `apps/scoreboard/portal/benchmark.js` can never be approved this
   way. Everything else is unchanged: the manifest names the issue and branch, and each file's
   `base_blob` and `approved_blob`; any other byte, file, branch or base fails closed.
2. New `.claude/scripts/tests/test_approved_js_change.py`, mirroring `test_approved_ts_change.py`.
3. The repo stack's gates in `.claude/sdlc.local.md` run the three approval test files with
   `uv run` (they need PyYAML through `run_gates.py`, which the PEP 723 header resolves).

## Tests (RED first)

- An exact approved `.js` change under `tests/` passes the append-only check; without the manifest
  it fails.
- An extra edit, another existing `.js` test, a wrong branch, a wrong base blob: each fails.
- A `.js` file outside a `tests/` directory, with a matching manifest, still fails.
- `run_gates.py repo` runs the three approval test files.

## Not in this change

No change to the Python range check, the TS/TSX rule, the manifest format, or `--skip-append-only`.
