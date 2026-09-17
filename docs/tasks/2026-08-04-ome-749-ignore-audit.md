---
id: OME-749
linear_url: https://linear.app/openmined/issue/OME-749/audit-dependabot-ignore-rules-so-they-expire-instead-of-silently
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-749 — audit Dependabot ignore rules so they expire

Sub-issue of `OME-733`.

This epic added `ignore` rules to `dependabot.yml`. Each is justified and each names its lifting
condition **in a comment** — which is the weakness. When `typescript-eslint` ships TS 7 support,
nothing notices; the ignore quietly becomes permanent.

Same shape as everything else this epic found: `apps/server` alerts accruing against a deleted
tree, `public-docs` lint red for months because nothing ran it, the stack card claiming OMDS after
the migration. **Unverified state drifting because no mechanism checks it.**

## What landed

- **`.github/dependabot-ignores.yml`** — a registry giving every ignore a *machine-checkable*
  blocker. Two kinds: `npm_peer` (read the blocking package's live peer range) and `ci_matrix`
  (read a workflow's version matrix). The second exists because `python >=3.14` is **not**
  upstream-blocked at all — we simply declined to test 3.14, and the registry says so plainly.
- **`.claude/scripts/audit_dependabot_ignores.py`** — the checker.
- **`repo-checks.yml`** — runs it, plus a **weekly schedule**, since the state being checked
  changes when upstream ships, not when we commit.

## Failure semantics — the key design decision

**Drift fails** (exit 1): an ignore with no registry entry, or an entry with no ignore, is our own
inconsistency and always fixable on the spot. **A liftable ignore only warns** (exit 0): failing a
PR because upstream published a release would train people to disable the check — strictly worse
than the rot it catches.

## Verified, including the negatives

| test | expected | result |
|---|---|---|
| green path | exit 0, all blocking | ✅ 5/5 |
| detects a lift | warn, exit 0 | ✅ |
| undocumented ignore | exit 1 | ✅ |
| orphaned registry entry | exit 1 | ✅ |

**A check that has never been seen to fail is not a check.**

## It found a real bug immediately — mine

The `ci_matrix` probe prints what it reads, exposing `scoreboard-tests.yml python-version =
['3.12']` against `['3.12','3.13']` for its siblings. `OME-747` moved scoreboard's Dockerfile to
**3.13** on the claim that "every Python matrix runs 3.12/3.13" — true of two apps out of three.
So scoreboard now ships 3.13 and tests 3.12: the exact failure `OME-747` set out to prevent,
caused by `OME-747`. Filed as `OME-750`.

Near-miss worth noting: the probe's first version read only *list* matrices and fell through to
"no matrix → still blocking" for scoreboard — right answer, wrong reason, which would have hidden
this permanently.

Ledger: `docs/work/2026-08-04-OME-749-ignore-audit.md`
