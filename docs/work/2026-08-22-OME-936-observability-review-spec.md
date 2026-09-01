---
ticket: OME-936
stack: repo
status: in_progress
started: 2026-08-22
finished:
---

# OME-936 — Write the observability & traceability review spec

## Intent

Capture the full debugging & traceability review of the monorepo (4-agent audit of
aigateway, aigateway-ui, scoreboard, screamingface-engine, packages, charts, CI, docs) as a
spec artifact, together with the owner's locked decisions (SigNoz backend; split traceback
posture; 30 d full-body retention; no error tracker yet) and the phased roadmap whose
Phase 0 was filed as epic `OME-935` with sub-issues `OME-936`–`OME-946`. The spec is the
prerequisite artifact for Phase 0 implementation (spec → plan → code) and the reference for
the Phase 1–3 epics to be filed later.

## Planned changes

- `docs/spec/2026-08-22-observability-traceability-review.md` — the review spec.
- `docs/tasks/2026-08-22-*.md` — 12 mirrors (epic `OME-935` + sub-issues `OME-936`–`OME-946`).
- `docs/observability-state-of-play.md` — team-facing brief derived from the spec, in the
  house top-level idiom (`scream-lisbon-digest.md`, `positioning.md`): no frontmatter, a
  `>` preamble naming audience and authority, cross-links to the spec and `ISSUES.md`.
  Doubles as a Slack canvas, so its matrix stays a monospace block rather than a Markdown
  table (canvases don't render tables).
- Later mirrors for the issues found during the empirical audit and the payload inventory
  (`OME-966`–`OME-970`, `OME-973`, `OME-976`).
- This ledger.

## Test plan

Docs-only unit — no code, no tests. Verification is review of the artifact against the
audit evidence and the locked decisions.

## Acceptance

- Spec records: per-app inventory with file:line evidence, integration quality, the
  k8s-live vs local-only matrix, the human-report→evidence analysis, all three locked
  decisions verbatim (including the aigateway posture amendment), and the Phase 0–3 roadmap
  with real issue IDs.
- All 12 `docs/tasks/` mirrors exist with correct frontmatter.
- Lands via PR; `OME-936` closed with the close template after merge.

## Review status

PR #688 is a **draft** and stays that way until the owner confirms readiness (2026-08-24).
The spec is under review; iterations land on this branch. Do not mark ready, do not merge,
and do not close `OME-936` until that confirmation is given in plain words.

## Maintenance pass — 2026-09-01 (branch kept mergeable)

The branch had drifted 166 commits behind `main` over the review window. Rebased onto
`origin/main` (clean, no conflicts) and corrected three things the drift caused. **Still a
draft — the standing instruction above is untouched.**

- **CI was red for a drift reason, not a content reason.** The `disable` job failed in 5 s
  with `can't open file '.github/scripts/preview_contract.py'`. That script exists on `main`
  and never existed on this branch, so the merge-ref run called a file the branch's tree did
  not have. The rebase is the fix; nothing in the PR's own content was wrong.
- **Duplicate mirror for `OME-945`, removed.** `OME-945`'s mirror reached `main` separately
  (executed with `OME-914`, filename `…-pypi-and-readme-issue-links.md`) while this PR sat
  open. Merging as-is would have left two files for one ticket asserting different statuses
  (`in_progress` on main vs `backlog` here). Deleted this branch's
  `…-OME-945-org-repoint.md`; kept `main`'s newer copy and carried over the one thing it
  lacked, the spec pointer every other Phase-0 mirror has.
- **Two mirrors restated against current Linear.** `OME-973` is **Done** (closed
  2026-08-26; implemented as epic `OME-1002`) — status and body updated. `OME-976` is
  **still Backlog and its status is left alone**, because it is genuinely unresolved: the
  epic shipped `LinearSink` but deliberately inert (rule 9 governs *selecting* the adapter,
  and every deployment keeps the `queue` default), so the decision is still owed. The mirror
  now records that consequence rather than implying the question went away.

The other nine Phase-0 sub-issue mirrors (`OME-937`–`944`, `946`) were re-checked against
Linear and are all still `Backlog` — accurate as written, left untouched.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (spec + 12 mirrors + ledger).
- **Commits:** one docs-only commit on `OME-936-observability-review-spec`; final sha
  recorded in the Linear close comment after squash-merge.
- **Gates:** docs-only; no stack gates apply.
- **Deviations:** Live Linear enforces single-select on the landing label group, so the
  Phase 0 epic `OME-935` carries `repo` instead of D9's "all affected landing labels"
  (each sub-issue carries its own leaf). Card/D9 reconciliation left to the owner.
