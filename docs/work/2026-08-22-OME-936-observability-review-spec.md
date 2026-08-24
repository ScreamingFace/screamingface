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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (spec + 12 mirrors + ledger).
- **Commits:** one docs-only commit on `OME-936-observability-review-spec`; final sha
  recorded in the Linear close comment after squash-merge.
- **Gates:** docs-only; no stack gates apply.
- **Deviations:** Live Linear enforces single-select on the landing label group, so the
  Phase 0 epic `OME-935` carries `repo` instead of D9's "all affected landing labels"
  (each sub-issue carries its own leaf). Card/D9 reconciliation left to the owner.
