# Plan: Gateway code provenance

Spec: `docs/spec/2026-11-23-gateway-code-provenance.md`. Ledger:
`docs/work/2026-11-23-gateway-code-provenance.md`. Branch `OME-2010-gateway-code-provenance`
(`gateway-code-provenance` until PR-open), now on
origin/main `d37932d61` (of its three commits after `a5a7986ec`, only OME-1989 changes an app;
the measurements it could move were taken again, see the ledger's Evidence), renamed at
PR-open with the Engine leaf's number (OME-2010; the Gateway leaf is OME-2011).
Stacks: `aigateway`, `screamingface-engine`.

## Preconditions

- Spec approved; its section 7 Q1 and Q3 answered.
- The branch is on the current origin/main. If origin/main moves past `a5a7986ec` before code
  starts, fast-forward and repeat the inventory, the history scan, the reserved overlap, the sink
  count and both Engine runs, and correct every base and line reference.
- No Tortoise model, query or migration change.
- Gates one stack at a time, from the worktree root, in an environment that matches CI
  (Python 3.12 and 3.13, `uv sync --dev`):
  `uv run .claude/scripts/run_gates.py <stack> --base origin/main`.
- Every prior test stays unchanged unless the owner approves its exact blobs (spec Q2). The
  approval manifest pins the branch name, so it is written under the Engine leaf after the
  PR-open rename, and the gates are run again with it.

## Phase 1: the Gateway vocabulary (TDD)

New `apps/aigateway/tests/unit/test_gateway_error_codes.py`, written first and red (no fixture):

- the code-write rules of spec 3.2 over `src/aigateway/`, `migrations/` excluded: dict literals,
  `code=` arguments, subscript stores, `.setdefault`, reviewed producers;
- the sink rules: every `HTTPException` detail, `JSONResponse` content and exception handler body
  is a string, a dict literal, a module constant bound to one, or a reviewed site;
- the reviewed table (file, function, reason, a fixed list or a producer) and the not-a-code
  table;
- the fixture: an object with sorted, disjoint `codes` and `retired` lists of plain identifiers;
  a `codes` entry no longer written fails;
- the self-test on synthetic modules, every case of spec 3.2.

Then `apps/aigateway/tests/fixtures/gateway_error_codes/codes.json`: `codes` from the check's own
output, read over by hand against the inventory in the ledger; `retired` the five codes of spec
3.1, with the history scan that found them rerun on the final base. Gate `aigateway`.

## Phase 2: the Engine rule (TDD)

- `world/connector.py` is already back on main (the shape screen was set aside when the branch
  moved to `a5a7986ec`): the closed rule replaces it, not extends it.
- `tests/unit/test_gateway_code_screen.py` (new in this unit), rewritten red first: every
  Engine test of spec 5 except parity, the exact benchmark values included.
- `tests/unit/test_gateway_codes_parity.py`, red first: the exact equality and the pinned overlap
  of spec 3.4.
- Then `world/gateway_codes.py` with `GATEWAY_CODES`, and `_upstream_code` reading it.
- Run the full Engine suite. Expected red: exactly the six prior test functions of spec 4. Any
  other red prior test is a finding to raise. Show the owner each one's current blob and the
  proposed change; change none without that approval.
- `.github/workflows/screamingface-engine-tests.yml`: the fixture directory in both path filters.
- Gate `screamingface-engine`.

## Phase 3: landing

- Ledger Outcome, both stacks' gates on 3.12 and 3.13 with no step skipped.
- Spec Q4 is answered: the hosted query is not run (owner, 2026-11-24), with its residual
  compatibility risk recorded in spec section 7. It blocks neither implementation nor merge.
- At PR-open, after the user confirms: the Engine leaf (primary) and the Gateway leaf under
  `OME-1306`, one `docs/tasks/` mirror each, the branch rename, the ledger's `ticket:`, the
  approval manifest under the Engine leaf, the gates again, `Refs:` both leaves.
- Deployment: none to order for this unit (spec 3.5). The pilot's PR #2016 reads this unit as
  landed once it merges.

## Done

Both stacks green with the diff reviewed; every spec 5 test present; the prior-test changes, if
approved, pinned by blob; spec Q4 recorded.
