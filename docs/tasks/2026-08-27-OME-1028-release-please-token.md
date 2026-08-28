---
ticket: OME-1028
linear_url: https://linear.app/openmined/issue/OME-1028/fix-release-please-token-so-releases-are-created-by-the-repository
stack: repo
status: in_progress
started: 2026-08-27
labels: [repo]
actor: agentic
who-acts: autonomous
type: task
priority: P2
---

# OME-1028 — Fix release-please token so releases are created by the repository

## Context

The `Release Please` workflow (`.github/workflows/release-please.yml`) has failed on
every push to `main` since 2026-08-23, blocking the releases for `url4 1.5.0` (#628)
and `screamingface-engine 1.4.0` (#644).

Error: `release-please failed: Resource not accessible by personal access token -
create-a-release`. The action step passes `token: ${{ secrets.RELEASE_PAT ||
secrets.GITHUB_TOKEN }}`; since `RELEASE_PAT` is set, the action always uses that
PAT, which has lost the permission to create GitHub releases (403). It worked through
2026-08-13 (last release created) and degraded by 2026-08-19 (first `Error adding to
tree` — a swallowed 403 on git-tree creation, per googleapis/release-please-action#938).

## Scope

- `.github/workflows/release-please.yml`: use `token: ${{ secrets.GITHUB_TOKEN }}`
  for the release-please action. The workflow already declares
  `permissions: contents: write, pull-requests: write`, sufficient for creating
  releases, tags, and release PRs; GITHUB_TOKEN cannot expire or lose scopes.
- Keep `RELEASE_PAT` on the lockfile-sync checkout step (a GITHUB_TOKEN push raises
  no workflow events, so the release PR would keep the red check it was opened with).

## Out of scope

- Rotating/regenerating `RELEASE_PAT` (owner action; the checkout step still needs it).
- Any application code.

## Definition of done

- Release-please action uses the repository token.
- Next push to `main` creates the pending releases (url4 1.5.0, screamingface-engine 1.4.0).
