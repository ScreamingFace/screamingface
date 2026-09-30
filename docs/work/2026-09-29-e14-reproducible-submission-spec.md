---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-29
finished:
---

# e14-reproducible-submission-spec — PRD/ERD set for epic OME-1307 (E14)

## Intent

Write the spec set (PRDs, ERD, contracts, test plan) for epic OME-1307, "Each leaderboard
submission is a reproducible research artifact". The set covers editable submission metadata
(E14a), a cache version per submitted run (E14b), result clustering, and system names with
revisions. It is the spec prerequisite (CLAUDE.md rule 3) before any plan or code. The
decisions come from an interview with the user on 2026-09-29 and from Irina's answers on the
ticket.

## Planned changes

- `docs/spec/2026-09-29-e14-reproducible-submission/00-overview.md`
- `docs/spec/2026-09-29-e14-reproducible-submission/erd.md`
- `docs/spec/2026-09-29-e14-reproducible-submission/prd/*.md` (2 component PRDs, 4 flow PRDs)
- `docs/spec/2026-09-29-e14-reproducible-submission/contracts.md`
- `docs/spec/2026-09-29-e14-reproducible-submission/test-plan.md`

## Test plan

- Docs only. Self-review against the prompt-planner Phase 6 bar: every product decision
  traces to an `ans:Qn` or to the ticket; every flow has at least 3 non-happy scenarios; every
  TDD plan starts RED and is ordered by risk.

## Acceptance

- The user reviews the set and approves it in plain words before a `docs/plan/` artifact starts.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. 10 files under
  `docs/spec/2026-09-29-e14-reproducible-submission/`: overview, erd, contracts, test-plan,
  and 6 PRDs (system-registry, cache-version-store, edit-metadata, submit-and-cluster,
  replay-pinned-run, publish-and-takedown). 130 scenarios, 136 TDD cases.
- **Review round 1 (2026-09-29):** DQ-1 accepted as `ans:Q17`. DQ-2 redesigned as `ans:Q18`:
  the user noted that cache answers never expire. So the 14-day heavy ledger became a
  per-key prompt table plus a thin run index, both kept forever. A freeze now has no deadline.
- **Commits:** `docs(spec): add E14 reproducible-submission PRD/ERD set` (spec only; plan and code not started).
- **Gates:** docs only. Self-review: tags valid, all test-id cross-references resolve, every
  PRD has ≥ 8 non-happy scenarios.
- **Review round 2 (2026-09-29):** the user approved the spec. Decisions Q19-Q24 recorded (one branch for spec + plans + code; fingerprint excludes `_sf_recipe`; 12 h grant limit accepted; prod identity = `cloudflare_headers`; new WIRING unit; engineering defaults X-3..X-25). Per-unit plans added under `docs/plan/2026-09-29-e14-reproducible-submission/` (17 units + index), written and reviewed by Opus agents.
- **Deviations:** the output folder is `docs/spec/<date>-<slug>/` (the repo convention)
  instead of the skill default `docs/plans/`. The interview grew the scope from the triage
  map's E14 (metadata plus cache version) to four parts (`ans:Q1`).
