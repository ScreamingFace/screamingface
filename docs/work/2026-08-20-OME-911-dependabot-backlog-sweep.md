---
ticket: OME-911
stack: repo
status: done
started: 2026-08-20
finished: 2026-08-20
---

# OME-911 — Dependabot backlog sweep after the ScreamingFace org transfer

## Intent

Eleven open Dependabot PRs had accumulated. Clear the backlog: close what is structurally
dead, land what is green, and hand the two genuinely-blocked PRs to their own work items
rather than force-merging or closing them. Repeat of OME-734 under epic OME-733.

## Planned changes

No source changes. PR-state actions only, plus this ledger.

- Close #641 (`apps/url4-cloud` — tree renamed away by `9b888579`; superseded by #645).
- Merge, in order: #554, #550 (uvicorn floor — first, they share `pyproject.toml`/`uv.lock`
  with #640/#637), then #557, #636, #632, #645, #638, #639.
- Leave #640 / #637 for OME-912 / OME-913, then `@dependabot rebase` and merge.

## Test plan

Not a code unit — no RED/GREEN. The gate is each PR's own CI:

- Re-check `mergeStateStatus == CLEAN` immediately before each merge (the earlier survey is
  a snapshot; main moves).
- After the sweep, `main` stays green on the lanes these PRs touch.
- `.claude/scripts/audit_dependabot_ignores.py` still passes — the 1:1 invariant between
  `dependabot.yml` and `dependabot-ignores.yml` must survive the sweep.

## Acceptance

- No open PR authored by `app/dependabot` except #640/#637 pending their sub-issues.
- #641 closed with the supersession reason recorded on the PR.
- No `--admin` merge; nothing merged ahead of green CI.

## Outcome

- **Actual files:** this ledger, plus the four `docs/tasks/` mirrors for this batch
  (see Deviations).
- **Result — 11 PRs resolved:**

  | PR | Outcome |
  |----|---------|
  | #641 | Closed as obsolete, reason recorded on the PR |
  | #554 #550 | Merged (uvicorn floor, first — they share files with #640/#637) |
  | #557 | Merged — last two `@v4` action pins in the repo |
  | #636 #632 #645 #638 #639 | Merged |
  | #640 #637 | Held for OME-912 / OME-913, then `@dependabot rebase` |

- **Gates:** each PR's own CI, re-checked `CLEAN` immediately before its merge. No `--admin`,
  nothing merged ahead of green CI. `run_gates.py` was run per-app on the two repair branches
  (scoreboard, aigateway) — both ALL GATES GREEN.
- **Deviations:**
  - The first merge attempt read `#550` as `UNKNOWN/UNKNOWN` and skipped it. That is GitHub
    recomputing mergeability asynchronously after `#554` landed, not a real block — the
    remaining merges were done through a poll-until-`CLEAN` loop instead of firing blind.
    Worth remembering: a single `gh pr view` right after a merge is not a reliable gate.
  - `docs/tasks/` mirrors for all four tickets in this batch (OME-910/911/912/913) are
    committed here rather than one-per-PR. They were missed at filing time; OME-913's PR had
    already merged, and adding pure-bookkeeping files to the two open code PRs would have
    restarted their CI for no engineering reason. Consolidating them in this sweep unit — the
    batch's bookkeeping unit — was the cheaper correction.
  - Line numbers quoted in OME-912/OME-913 at filing time drifted (`store.py:65` → `:72`)
    because main moved during the sweep. No behavioural difference.
