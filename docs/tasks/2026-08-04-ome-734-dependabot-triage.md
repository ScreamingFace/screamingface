---
id: OME-734
linear_url: https://linear.app/openmined/issue/OME-734/merge-the-green-dependabot-prs-and-clear-the-subsumed-pair
status: in_review
type: task
priority: P1
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-734 — merge the green Dependabot PRs and clear the subsumed pair

Sub-issue of `OME-733` (Dependabot compliance + alert burndown).

Triage of all 16 open Dependabot PRs against 100 open security alerts. Merges only — no code
changes, and nothing is closed here.

## Why merging, not closing

Only **2 of 16** PRs are genuinely subsumed — #433 (cryptography →48.0.1, superseded by #436
→49.0.0) and #455 (next →16.2.11, superseded by #457 →16.2.12). Both are **green**; both
supersedents are **red**.

Closing a Dependabot PR suppresses recreation for that version. Since each subsumed PR is the
only green fix for a high-severity alert, closing them would leave those alerts unfixed for as
long as the group PRs stay broken. Merging reaches the same end state with no exposure window —
Dependabot rebases the group PRs and drops the redundant entries by itself.

## Order

1. #433, #455 — the subsumed pair, first.
2. Green singles: #437 urllib3, #435 aiohttp, #431 starlette, #430 starlette,
   #460 brace-expansion, #432 postcss, #422 next.
3. Green groups: #453 github-actions, #456 url4-cloud, #454 packages/url4, #397 scoreboard.

`#397` dates from 2026-07-14 — let Dependabot rebase before merging. `#453` carries GitHub
Actions majors and also clears the Node 20 deprecation warnings in every workflow log.

## Result

**17 PRs merged, open alerts 100 → 51.** `aigateway-ui`, `screamingface-studio/frontend`,
`scoreboard` and `public-docs` went fully clean. Of the 51 left, **38 are the stale
`apps/server` tree** — only 13 are real.

Four more merges than planned: each merge made Dependabot re-evaluate and open a *better* PR.
#469 raised cryptography to **50.0.0** (above the #436 group's 49.0.0) minutes after #433 landed.
#422, #435 and #457 were closed **by Dependabot** as superseded — confirming that merging rather
than closing is what lets the bot converge.

## Non-goals

`#439` is broken rather than redundant and is closed under `OME-740`. The red group PRs #436
and #457 are repaired under `OME-735` and `OME-736`.

Ledger: `docs/work/2026-08-04-OME-734-dependabot-triage.md`
