---
ticket: OME-1614
stack: repo
status: done
started: 2026-10-21
finished: 2026-10-22
---

# OME-1614 — public docs for pinned-cache replays and submission metadata

## Intent

Teach the 0.1.7 SDK: `sf.evaluate(pinned_cache=…)` replays, seeds, partial replays and author and
paper metadata; drop `sf.reproduce` and the `frozen_copy_id` attribute. Spec
`docs/spec/2026-10-21-OME-1614-public-docs-pinned-cache.md`, plan
`docs/plan/2026-10-21-OME-1614-public-docs-pinned-cache.md`. The OME-1614 mirror rides in PR #1519.

## Planned changes

Plan table (10 pages, the SDK source baseline, and `CONTEXT.md`).

2026-10-22: owner authorized implementation. Fast-forwarded the existing docs worktree to
current main, including the reviewed OME-1613 SDK. Initially opened as a draft pending the release
and released-SDK verification; validated locally with fake transports and browser-rendered pages.

## Test plan

Spec "Checks".

## Acceptance

As on the ticket.

## Outcome

- **Actual files:** ten concept, guide and API pages listed in the spec; glossary in
  `CONTEXT.md`; `public-docs/src/navigation/sf-client.ts` points at the merged SDK source;
  this spec, plan, ledger and task mirror. No SDK or service code changed.
- **Commits:** `docs: document pinned-cache replay and submission metadata` (Refs: OME-1614).
- **Gates:** `npm run build` (Vue type check + Vite) and `npm run lint` (oxlint + eslint)
  pass. `uv run .claude/scripts/run_gates.py repo` passes all five repository gates and
  the append-only check. `git diff --check` passes.
- **Examples:** scratch validation parsed 46 executable Python blocks on the changed pages.
  Thirteen scenarios ran with the merged SDK and fake Engine/leaderboard transports:
  pinned-cache and score-id replay, no-record replay, private score fallback, partial replay,
  unsubmitted capture, four replay-error outcomes, two submission snippets and metadata edits.
  Submission statements used a prepared CandidateResult; their fresh-evaluation preambles
  were syntax checked only. Socket connections were forbidden. No live submissions,
  reproduction records or provider calls were made.
- **Browser:** Playwright fallback (no browser connected to the app). Inspected the replay
  guide in dark mode and author/paper metadata and replay errors in light mode; the guide's
  Errors reference link resolves. Route smoke checks cover the other eight changed pages.
  No application errors; localhost analytics emits its expected ignored-event warning.
- **Deviations:** source reconciliation corrected the ticket's absolute email privacy claim:
  public author ids retain full addresses on local-part collisions. Also documented that
  replacing paper metadata without a URL clears the link. Advanced the sidebar source
  baseline because the old commit predates the documented API.

## Original publication plan (superseded below)

Owner initially requested ready-for-review on 2026-10-22 with release checks as merge prerequisites.
PyPI still serves SDK **0.1.6**, checked 2026-10-22. After the release
containing #1519 (planned **0.1.7**), verify the examples against that release, including live
replay on the staging fixture in the spec, and update the sidebar to the verified release.
The portal instructions also require the Reproduce snippet update in **OME-1655 / PR #1522**
(open and draft at merge). The original plan held merge until those dependencies were available.
The owner later authorized the docs-only merge; released-SDK verification remains outstanding as rollout work.

## Independent review (2026-10-22)

A separate reviewer, without the implementation conversation, compared `bc3504d3f` with the SDK
and scoreboard source. One P3 finding: the five reserved metadata keys enforce their types and
limits in either metadata object. Clarified that rule. Also reconciled adjacent reference prose
about author-email collisions, fresh url4 evaluations versus replay, and metadata edit logs.
No other introduced blocking findings. The owner explicitly requested marking PR #1535 ready
for review; at that point, merge and deployment were not yet authorized.

The independent reviewer rechecked the corrections and confirmed the finding is resolved with
no new issue. Build, lint, all repo gates and `git diff --check` pass after the corrections.

## GitHub / Linear closure (2026-10-22)

Owner requested a fresh code review and merge if clean, superseding the earlier release hold.
A new independent reviewer checked the full diff at `8567860cf` against the SDK and scoreboard
implementation and found no actionable issues. All GitHub CI checks passed. PR #1535 merged
as `8546bcbbd4d76edb85a5d550f2f8c8948fe40cdb`.

At the owner's request, synced Linear OME-1614 to Done, attached the merged PR and filed the
completion comment with commits, checks and deviations. E14 remains In Review. OME-1655 stays
open and now explicitly tracks released-SDK/live docs-example verification and the sidebar
release update. Neither the SDK release nor production replay verification is claimed complete.

This closure updates only the task mirror and ledger. Validation: repository gates and
`git diff --check`.
