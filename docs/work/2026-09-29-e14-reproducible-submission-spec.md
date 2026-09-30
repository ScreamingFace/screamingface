---
ticket: OME-1433   # E14 leaf under epic OME-1307 (filed at PR-open, 2026-09-30)
stack: repo
status: done   # planned | in_progress | done | blocked
started: 2026-09-29
finished: 2026-09-30
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
- **Close-out (2026-09-30):** the spec, the plans and all 17 units are on the one branch
  `e14-reproducible-submission-spec` (D1), with the final-check fixes (RP-X1, RP-X2, FS-1,
  X-SEC-1, MRA-1, MRA-2). Unit ledgers in `docs/work/`: `2026-09-29-e14-{sb-schema,
  system-registry, gw-capture, sb-meta, gw-freeze, eng-freeze, sdk-meta, sb-submit, gw-replay,
  eng-replay, sdk-submit, sb-grants, sb-publish, sdk-replay, wiring, e2e}.md` (SB-registry is
  `e14-system-registry.md`; URL4-fp is `2026-09-29-url4-system-fingerprint.md`), and the
  final-check ledgers
  `2026-09-30-e14-final-{apps-scoreboard, apps-screamingface-engine, packages-screamingface}.md`.
  The decisions D1 to D8 are in `docs/plan/2026-09-29-e14-reproducible-submission/00-index.md` §7
  (D8 is also spec `00-overview.md` §4.2 Q25). The status, the gate and E2E results, and the open
  items for the owner are in `00-index.md` "Status (2026-09-30)". The Linear leaf issue, the
  `docs/tasks/` mirror and the `OME-N` branch rename are deferred by the user, so `ticket` stays
  `unfiled`.
