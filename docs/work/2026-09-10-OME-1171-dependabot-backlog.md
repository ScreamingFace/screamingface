---
ticket: OME-1171
stack: repo
status: in_progress
started: 2026-09-10
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
