---
ticket: OME-1443
stack: repo
status: done
started: 2026-10-01
finished: 2026-10-01
---

# pre-push-base-fallback — the pre-push hook compares against the remote's main, never a local `main`

## Intent

Before every push, `.githooks/pre-push` works out which stacks the branch changed and runs each
of their gates. It finds the changes by diffing against `origin/main`. A clone whose remote is
named `upstream` has no `origin/main`, so the hook fell back to the local `main` branch. A local
`main` that lags the remote by a few commits makes every remote commit since look like this
branch's change, so a docs-only push ran the engine, aigateway and aigateway-ui gates (a full
~4,650-test engine suite with coverage, plus an npm build). Seen 2026-10-01: local `main` 8
commits behind `upstream/main`, those 8 commits touching three stacks. The fix picks the base by
history, not by remote name: among every `<remote>/main`, the one the branch has the fewest
commits on top of. It stops with a clear message if there is none, and never uses a local branch.

## Planned changes

- `.githooks/pre-push`: resolve the base as the `<remote>/main` with the fewest commits between it
  and HEAD; no local-branch fallback; exit 1 with a fix-it message when no remote main exists.
- `.claude/scripts/tests/test_pre_push.py` (new): runs the real hook in throwaway git repos with a
  stub `uv` that records which stacks were gated.
- `.claude/sdlc.local.md`: register the new test under the `repo` stack's gates.

## Test plan

- A docs-only branch in a clone whose remote is `upstream` and whose local `main` lags: no stack
  is gated (RED on main: engine gated).
- Same with the remote named `origin`: no stack is gated.
- Same with a remote named `sc-remote`: no stack is gated (any name works).
- Two remotes, the stale one named `upstream`: the main the branch was cut from wins.
- Two remotes, the stale one named `origin` so it sorts first: it still loses (history, not order).
- A branch that really changes the engine: exactly the engine is gated, with `--base` set to the commit the branch was cut from.
- main moves on after the cut and adds an engine test: the checks still get the branch point, not main's latest commit.
- No remote main at all: the hook exits 1 and names both refs, and gates nothing.

## Acceptance

- The eight tests pass; the `upstream` one fails on the original hook, and the `sc-remote` and stale-remote ones fail on a fixed-name-list version.
- `run_gates.py repo` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `.githooks/pre-push`, `.claude/scripts/tests/test_pre_push.py`,
  `.claude/sdlc.local.md`, this ledger and the task mirror.
- **Commits:** `701de1985` fix(repo): compare the pre-push hook against the remote's main, never a local main · `b0da301a7` fix(repo): pick the pre-push base by history, so any remote name works; plus this ledger and the mirror.
- **Gates:** RED first on the unfixed hook: 1 passed, 3 failed (the docs-only `upstream` branch gated
  `screamingface-engine main`). The first fix tried `upstream/main` then `origin/main` by name; on
  review it was replaced by the by-history pick, with two RED tests on the name-list version (the
  `sc-remote` push was blocked; the stale `upstream` won and gated the engine). GREEN after: 7
  passed (the seventh, a stale `origin` that sorts first, added on review: a hook that took the first `<remote>/main` passed the other six). A review then found the checks got the remote main's latest commit, which run_gates.py's append-only check diffs against the working tree, so a test main changed after the cut read as this branch's edit. The hook now passes `git merge-base <remote>/main HEAD`; two tests went RED on the tip (`screamingface-engine upstream/main`) and GREEN after: 8 passed. `run_gates.py repo --base upstream/main`: ALL GATES GREEN.
- **Deviations:** the base pick changed mid-review from a fixed name list to the by-history pick
  (owner decision, 2026-10-01), so any remote name and a fork with a stale remote both work. On review, the hook also hands the checks the branch point instead of the remote main's latest commit. The `repo` stack is still not in the hook's stack list, so the hook never
  runs the repo gates itself; left as is (out of scope).
