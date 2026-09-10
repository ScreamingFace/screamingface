---
ticket: OME-1171
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1171 — Merge the safe Dependabot backlog and publish an owner triage

## Intent

18 Dependabot PRs sit open, the oldest from 2026-09-01, nine of them security updates and two
carrying unauthenticated-RCE advisories for Next.js. The backlog is not uniformly safe: seven PRs
edit a manifest, move a framework version, or ship a native binary in a tree owned by another
maintainer per `.github/CODEOWNERS`, and one (#803) is red because it trips a deliberate LiteLLM
runtime guard. This unit merges only the unambiguously safe tail and turns the rest into a written,
per-owner triage so the remaining decisions land with the people who own them.

Zero open PRs is deliberately NOT the goal. `reviewDecision` is empty and no ruleset blocks merge,
so CODEOWNERS is advisory — nothing platform-side would stop us squashing another team's framework
bump. Closing them instead does not stick: Dependabot recreates a closed PR unless
`.github/dependabot.yml` gains an `ignore:` with a 1:1 rationale in `.github/dependabot-ignores.yml`
whose `blocker.kind` is `npm_peer` or `ci_matrix` (audited by `repo-checks.yml`), and nothing in
this backlog fits that schema.

## Planned changes

No application code. Repo writes are confined to this branch:

- `docs/plan/2026-09-10-dependabot-backlog-triage.md` — the triage document, organised by CODEOWNER
- `docs/work/2026-09-10-OME-1171-dependabot-backlog.md` — this ledger
- `docs/tasks/2026-09-10-OME-1171-dependabot-backlog.md` — the Linear mirror

Merged directly on GitHub (10 PRs, lockfile-only, no manifest edit, green CI):
#811, #804, #802, #799, #798, #810, #809, #864, #807, #860.

## Test plan

No new tests — this unit ships no executable code. The safety argument rests on each merged PR's
own CI, which must be green at merge time, and on the diff shape: `uv.lock` / `package-lock.json`
only, verified per PR with `gh pr view <n> --json files`.

Two clusters share a lockfile and must be merged in order, re-checking `mergeStateStatus` between
merges and issuing `@dependabot rebase` on DIRTY/BEHIND:

- `apps/screamingface-engine/uv.lock`: #811 -> #804
- `apps/screamingface-studio/frontend/package-lock.json`: #864 -> #807

## Acceptance

- The 10 PRs above are squash-merged, each on green CI; never `--admin`.
- `gh pr list --author "app/dependabot" --state open` returns 8 (7 owner-gated + #803), down from 18.
- The triage doc names, for every one of those 8, the owner, the ask, and the specific risk.
- Three follow-up issues exist and are referenced from the triage doc: the LiteLLM 1.100 guard
  re-verification (supersedes #803), the packaged-litellm pin split, and the unpinned helm renderer.

## Outcome

- **Actual files:** as planned — `docs/plan/2026-09-10-dependabot-backlog-triage.md`,
  this ledger, and `docs/tasks/2026-09-10-OME-1171-dependabot-backlog.md`. No application code.
- **Commits:** `0c3a9b69` — docs(repo): triage the Dependabot backlog by CODEOWNER (PR #895)
- **Merged PRs (10):** #811, #802, #799, #798, #810, #809, #864, #860, then the two cluster
  siblings #804 and #807. Each `mergeStateStatus: CLEAN` and green at merge time; squash, no
  `--admin`.
- **Gates:** no `run_gates.py` — this unit ships no executable code. Verification was CI instead:
  - PR #895: all checks pass (`CodeQL`, `Analyze` × 4, `plan`), `mergeStateStatus: CLEAN`.
  - `main` after the sweep: no failing repo workflow. `screamingface-engine-tests`,
    `ScreamingFace E2E Replay`, `Dev build screamingface-engine` and `Release Please` all green.
  - Confirmed the bumps actually landed: `apps/screamingface-engine/uv.lock` on `origin/main` now
    shows tornado 6.5.8, pydantic 2.13.5, ruff 0.16.6.
- **Deviations:**
  1. **No `@dependabot rebase` was needed.** Both lockfile clusters (#811 -> #804,
     #864 -> #807) re-reported `CLEAN` after the head merged, because the grouped bumps touch
     disjoint lock entries. The rebase step in the plan went unused.
  2. **Two cancelled runs on #811's merge commit** (`screamingface-engine-tests`,
     `Dev build screamingface-engine`) — concurrency-cancelled when #804 merged into the same
     tree 54s later. Not a gap: #804's runs cover a commit containing both bumps and are green.
  3. **Two red `Dependabot Updates` runs on `main`**, for nanoid and js-yaml. These are
     Dependabot's own post-merge security-refresh jobs, triggered by the very merges that fixed
     the advisories — the logs read "Checking if js-yaml 4.3.2 needs updating" and "Found no
     dependencies to update", then exit `unknown_error`. Dependabot-side race, not our CI and not
     a regression on `main`.
  4. **The unit did not reach zero open Dependabot PRs**, by design — see the Intent section.
     18 -> 8. The remaining 8 are owner-gated and handed over in the triage doc.
- **Follow-ups filed:** OME-1172 (LiteLLM 1.100 guard re-verification, supersedes #803),
  OME-1173 (packaged litellm pin drift, blocked by OME-1172), OME-1174 (helm renderer unpinned
  in CI — `version: latest` currently resolves v4.2.4).
