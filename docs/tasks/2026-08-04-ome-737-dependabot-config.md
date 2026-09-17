---
id: OME-737
linear_url: https://linear.app/openmined/issue/OME-737/regroup-dependabotyml-so-security-updates-group-and-majors-split-out
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-737 — regroup dependabot.yml so security updates group and majors split out

Sub-issue of `OME-733`. The structural fix of the epic: everything before this cleared a backlog,
this stops it re-forming.

## The two faults

**1 — `groups` did not apply to security updates.** It defaults to
`applies-to: version-updates`, so every security fix arrived ungrouped, one PR per package. That
was the entire single-package backlog this epic cleared: #437 #435 #433 #431 #430 #455 #422 #460
#432.

**2 — majors rode with patches.** One breaking major held security bumps hostage, *and* a major
slipped in under cover of them — both in the same PR. In `OME-736`, the react/react-dom 19.2.8
security bumps sat behind an ESLint 10 crash while that same PR quietly carried a TypeScript 5→7
compiler rewrite.

Three groups per ecosystem now: `-security` (`applies-to: security-updates`), `-minor`
(`minor`+`patch`), `-major`. A red `-major` PR can sit indefinitely while `-security` and `-minor`
keep flowing.

## Coverage

**6/12 → 10/12 manifests.** Docker **1/4 → 4/4**. Added `npm` → `/public-docs`, which landed only
after `OME-738` (#484) gave that tree a CI lane — a directory should not be listed until something
can gate what it produces.

## The comment that had to change

The old file excluded `apps/screamingface-studio/frontend` because "it has no CI lane, so a
dependency bump there would land with nothing to verify it". Sound intent, broken mechanism:
**security updates ignore the `directory:` allowlist**, which is exactly how #422 existed in that
very tree. Omitting a directory buys no silence — only the absence of routine version bumps, while
security PRs arrive anyway, unverified.

## Deferred

Both `screamingface-studio` entries (npm + cargo) pending `OME-739`. If that tree is dormant,
deleting it closes the repo's last open alert (`glib`) and retires the question.

## Verified

11 entries, **zero ungrouped**; every directory exists and holds a manifest of its declared
ecosystem; every group declares an explicit `applies-to`. This matters because a malformed
`dependabot.yml` fails **silently** — it stops producing PRs rather than erroring, which looks
identical to "nothing to update".

Ledger: `docs/work/2026-08-04-OME-737-dependabot-config.md`
