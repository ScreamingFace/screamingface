---
ticket: OME-1947
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# pinned-cache-retention-docs — the docs state the retention rule of the pinned cache (unit C3)

## Intent

The public docs say that a pinned cache is kept forever. That is no longer true. Unit C3 states the rule: a pinned cache that a leaderboard score uses is kept; one with no submitted score is deleted 90 days after it is sealed. No date and no person is named (Q32).

Spec: `docs/spec/2026-11-16-frozen-copy-retention/`. Plan: `docs/plan/2026-11-17-frozen-copy-retention-stack-c.md` (owner approved 2026-11-17).

## Planned changes

- `public-docs/src/pages/learn/CachingPage.vue`
- `CONTEXT.md` (Pinned Cache)
- `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` (rows Q33 to Q36, F1, F2)
- `apps/aigateway/src/aigateway/core/frozen_copy/models.py` (docstring lines 6 to 7)

## Test plan

No automated test (text only). Checks:
- no "kept forever" and no "permanent" near "pinned cache" in `public-docs/`;
- the four rows are equal to `prd/expired-copy-replay.md` §4.3;
- `public-docs`: `npm ci`, `npx oxlint .`, `npx eslint .`, `npm run build`;
- `run_gates.py aigateway` (the docstring).

## Acceptance

- The checks above are green.
- An independent review against `prd/expired-copy-replay.md` §3.1 and §4.3 has no open finding.
- Merge only after C1 is merged (Q32).

## Notes at start

- Owner order of 2026-11-17: both plans approved; build stacks B and C in parallel.
- The branch is cut from the stack A branch (commit a06fc9802), because pull request #1911 is not
  merged. After the merge of #1911, rebase the branch onto `origin/main`. The local gates use
  `--base` at the commit below this unit.
- The `tortoise-dev` companion skill is not installed on this machine. Code that touches the ORM
  follows the house pattern that the plan names.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: the text is written, reviewed and committed on the branch
`OME-1947-pinned-cache-retention-docs`. `status` stays `in_progress` until the pull request is
merged.

- **Actual files:** as planned, plus `public-docs/src/pages/sf-client/api/LeaderboardsPage.vue`
  (review finding 4).
- **Commits:** one commit, `docs: state the retention rule of the pinned cache (OME-1947)`.
- **Gates:** `public-docs`: `npm ci`, `npx oxlint .`, `npx eslint .`, `npm run build` and
  `npx prettier --check` on the two changed pages: all green.
  `uv run .claude/scripts/run_gates.py aigateway --base a06fc9802` → ALL GATES GREEN (the model
  docstring).
- **Design review:** verdict ACCEPT-WITH-FIXES, 6 findings (4 minor, 2 nit), none major. All 6
  are applied.
- **Deviations:**
  - The page has two new paragraphs, not one: the retention rule, and which submit is refused.
  - The page says "was not sealed" where the spec says "was not closed": the page defines the
    word "sealed" and never the word "closed".
  - Spec corrections in the public text (review findings 1 and 2; the spec text of R2 and R4 was
    not exact for a local scoreboard, which stores a Score with its pinned cache id,
    `prd/score-claim.md` K-16):
    - the refusal of a submit is stated for the hosted leaderboard only;
    - "because no hosted leaderboard score can use it there" (the spec: "no score");
    - the glossary says "while a hosted Leaderboard Score names it" (the spec: "a Leaderboard
      Score").
  - The message of a failed replay is described as "says it expired" (the engine text says
    "the frozen copy expired").
  - "Submit the score within those 90 days" comes before the sentence about a pinned cache that
    was sealed before the rule (the spec order made it read as a rule for those only).
  - Scope addition (review finding 4): the two lists of the causes of `frozen_copy_unavailable`
    (`learn/CachingPage.vue`, `sf-client/api/LeaderboardsPage.vue`) now name an expired copy.
  - Merge only after C1 is merged (Q32). The docstring of `models.py` conflicts with no line of
    C1, but rebase after C1.
