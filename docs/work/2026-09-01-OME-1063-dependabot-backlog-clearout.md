---
ticket: OME-1063
stack: repo
status: in_progress
started: 2026-09-01
finished:
---

# OME-1063 — clear the Dependabot backlog, then cut its refill rate

## Intent

The repo had 31 open PRs; 8 were Dependabot, roughly a quarter of the board. This unit
clears the standing pile and files the follow-ups needed so it does not immediately
refill. It carries the `docs/tasks/` mirrors for both filed items — deliberately one
branch rather than two, since adding PRs to a PR-count problem is self-defeating.

## Planned changes

- `docs/tasks/2026-09-01-OME-1062-aigateway-minor-bump-red.md` (new)
- `docs/tasks/2026-09-01-OME-1063-dependabot-volume.md` (new)
- `docs/work/2026-09-01-OME-1063-dependabot-backlog-clearout.md` (this file)

The `.github/dependabot.yml` edit itself is NOT in this branch — it is OME-1063's own
implementation and needs its own RED/GREEN loop against a real Dependabot run.

## Test plan

Docs-only branch; no code under test. The verification is the board state itself:

- `gh pr list --state open --json number --jq length` returns 24 (was 31).
- No open Dependabot PR except #774.
- Every merged PR reports `MERGED` with a `mergedAt`.

## Acceptance

- The seven green Dependabot PRs are merged, not closed.
- The one red Dependabot PR is diagnosed under its own ticket, not closed blind.
- Both filed items exist in Linear AND as `docs/tasks/` mirrors.

## Findings that shaped the work

Recorded because two of them contradicted the plan we started from:

1. **Zero file overlap across the seven green PRs** — `apps/scoreboard/uv.lock`,
   `packages/url4/uv.lock`, `apps/screamingface-engine/uv.lock`,
   `public-docs/package-lock.json`, `apps/aigateway-ui/package-lock.json`,
   `packages/screamingface/uv.lock`, one workflow file. Per-directory lockfiles are what
   made merging them in any order safe, with no rebase between.
2. **`mergeStateStatus` is lazily computed.** A bulk `gh pr list` returns `UNKNOWN` for
   every PR; only a per-PR `gh pr view` (often a second call) resolves it. All seven were
   `MERGEABLE/CLEAN`, which also proved branch protection was not requiring a review.
3. **Closing release-please PRs does not cancel a release — it recreates them.** The
   original intent for this session was to close all six. Repo history refutes it: #375
   (aigateway) and #449 (scoreboard) were closed on 2026-08-05, and #512 and #511 were
   created the same day. The two oldest PRs on the board are the product of that exact
   action. Twenty-four release PRs have been merged, most recently 2026-08-27, so
   "unmerged means unwanted" does not hold either — the four stale components simply have
   no release owner. Only merging, or deregistering the component in
   `release-please-config.json`, removes them for good. Left untouched by owner decision.
4. **`.github/dependabot.yml` carries a live bug**: `/packages/screamingface` declares a
   group with no `applies-to:`, the OME-733 fault every other ecosystem had fixed. Folded
   into OME-1063's scope.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — two `docs/tasks/` mirrors plus this ledger.
- **Commits:** <sha — message>
- **Gates:** docs-only; repo lint/CI on the PR.
- **Deviations:** the release-please half of the original request was dropped on evidence
  (finding 3) and the owner's call; this branch does not touch `release-please-config.json`.
