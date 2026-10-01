---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-01
finished:
---

# pre-push-base-fallback — the pre-push hook compares against the remote's main, never a local `main`

## Intent

Before every push, `.githooks/pre-push` works out which stacks the branch changed and runs each
of their gates. It finds the changes by diffing against `origin/main`. A clone whose remote is
named `upstream` has no `origin/main`, so the hook fell back to the local `main` branch. A local
`main` that lags the remote by a few commits makes every remote commit since look like this
branch's change, so a docs-only push ran the engine, aigateway and aigateway-ui gates (a full
~4,650-test engine suite with coverage, plus an npm build). Seen 2026-10-01: local `main` 8
commits behind `upstream/main`, those 8 commits touching three stacks. The fix tries
`upstream/main`, then `origin/main`, and stops with a clear message if neither exists. It never
uses the local branch.

## Planned changes

- `.githooks/pre-push`: resolve the base from `refs/remotes/upstream/main`, then
  `refs/remotes/origin/main`; no local-branch fallback; exit 1 with a fix-it message when neither
  exists.
- `.claude/scripts/tests/test_pre_push.py` (new): runs the real hook in throwaway git repos with a
  stub `uv` that records which stacks were gated.
- `.claude/sdlc.local.md`: register the new test under the `repo` stack's gates.

## Test plan

- A docs-only branch in a clone whose remote is `upstream` and whose local `main` lags: no stack
  is gated (RED on main: engine gated).
- Same with the remote named `origin`: no stack is gated.
- A branch that really changes the engine: exactly the engine is gated, with `--base upstream/main`.
- No remote main at all: the hook exits 1 and names both refs, and gates nothing.

## Acceptance

- The four tests pass; the first fails on the unfixed hook.
- `run_gates.py repo` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `.githooks/pre-push`, `.claude/scripts/tests/test_pre_push.py`,
  `.claude/sdlc.local.md`, this ledger and the task mirror.
- **Commits:** `fix(repo): compare the pre-push hook against the remote's main, never a local main`.
- **Gates:** RED first on the unfixed hook: 1 passed, 3 failed (the docs-only `upstream` branch gated
  `screamingface-engine main`). GREEN after: 4 passed. `run_gates.py repo --base upstream/main`:
  ALL GATES GREEN.
- **Deviations:** none. The `repo` stack is still not in the hook's stack list, so the hook never
  runs the repo gates itself; left as is (out of scope).
