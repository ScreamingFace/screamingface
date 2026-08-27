---
ticket: OME-901
stack: repo
status: done
started: 2026-08-27
finished: 2026-08-27
---

# OME-901 — Design retained operation accounting

## Intent

Turn the runtime-accounting lineage audit into an owner-approved retained Report contract and an
ordered Engine → Client implementation plan without changing production code.

## Planned changes

- Write `docs/spec/2026-08-27-OME-901-operation-accounting.md`.
- Write `docs/plan/2026-08-27-OME-901-operation-accounting.md`.
- Correct the superseded architecture conclusion in the lineage ledger and task mirror.
- Make OME-901 the cross-cutting parent and file one implementation child for ScreamingFace Engine
  and one for the Python Client.

## Test plan

- Check all Markdown with `git diff --check`.
- Re-read the spec against the approved GrillMe decisions and the lineage evidence.
- Verify every child has one landing label, one actor, one who-acts label, the project, priority,
  assignee, parent, task mirror, and dependency relation.

## Acceptance

- The spec names the exact ownership, scope lifetime, wire shape, unknown/ambiguity behavior,
  cache semantics, failure behavior, privacy boundary, UI boundary, and non-goals.
- The plan separates Engine and Client PRs and requires explicit implementation approval.
- Linear and repo mirrors describe the same dependency order.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `docs/spec/2026-08-27-OME-901-operation-accounting.md`
  - `docs/plan/2026-08-27-OME-901-operation-accounting.md`
  - `docs/tasks/2026-08-20-OME-901-evaluation-cost-breakdown.md`
  - `docs/tasks/2026-08-27-OME-1030-engine-operation-accounting.md`
  - `docs/tasks/2026-08-27-OME-1031-client-operation-accounting.md`
  - `docs/work/2026-08-27-OME-901-runtime-accounting-lineage.md`
- **Commits:** none
- **Gates:** `git diff --check`; stale-design phrase scan; Linear parent/labels/child/dependency
  re-read through MCP.
- **Deviations:** exact Case wall time was removed after source inspection proved there is no
  Case-start lifecycle boundary. A second adversarial pass also removed a new Engine timer,
  parallel grading `CaseOperation` rows, complete Candidate fingerprints, member duration,
  failed-path interception, and exact token-remainder claims. Existing Gateway latency is retained
  as Provider time. No production or test code changed.
