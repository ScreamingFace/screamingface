---
ticket: OME-1254
stack: repo
status: done
started: 2026-09-22
finished: 2026-09-22
---

# OME-1254 — Flag class-based test files in code review

## Intent

Codify the repo's test style convention — plain `test_` functions, no `class Test`
grouping — into the shared review agent, so the next class-style test file gets a
Minor finding at review time instead of being discovered post-merge. Confirmed
pattern: 252/260 engine unit test files (and all of SDK/scoreboard/url4) are
function-style; the two exceptions are single-train style islands (contracteval/spine
family, aigateway `usage_accounting/`) that neighbouring PRs then copied — most
recently the migration goldens in PRs `#1004`/`#1005`, which the owner asked to have
flattened during the OME-1236 stack review.

## Planned changes

- `.claude/agents/sf-code-review.md` — one bullet appended to the Lane 7 (test
  honesty) list naming the convention, its evidence, and the Minor severity; no
  retro-flagging of existing class-style files.
- `docs/tasks/2026-09-22-flag-class-based-tests-in-review.md` — mirror.
- This ledger.

## Test plan

- Docs-only change: no runtime tests. Verification is a source check — the counts in
  the bullet re-derived from the tree (`git grep -lE "^class Test" -- apps/ packages/`)
  and the bullet's placement inside Lane 7's bullet list.

## Acceptance

- The review agent file carries the convention with the confirming review cited
  inline, lands via PR (never a direct edit on main), and the mirror + this ledger
  close with it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned
- **Commits:** cc203d88 — docs(repo): teach the review agent the plain-function test convention
- **Gates:** docs-only; repo hooks green on commit; counts re-derived from the tree (`git grep -lE "^class Test"` → 8 engine + 10 aigateway files)
- **Deviations:** none
