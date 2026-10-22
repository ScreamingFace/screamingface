---
ticket: OME-1614
stack: repo
status: in_progress
started: 2026-10-21
finished:
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
current main, including the reviewed OME-1613 SDK. Keep the PR draft until the release and
released-SDK verification; validate locally with fake transports and browser-rendered pages.

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

## Before publication

Keep the PR draft. PyPI still serves SDK **0.1.6**, checked 2026-10-22. After the release
containing #1519 (planned **0.1.7**), verify the examples against that release, including live
replay on the staging fixture in the spec, and update the sidebar to the verified release.
The portal instructions also require the Reproduce snippet update in **OME-1655 / PR #1522**
(currently open and draft). Merge only after those dependencies are available. This ledger
remains in progress because released-SDK verification is still outstanding.
