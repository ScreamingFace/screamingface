---
ticket: OME-1578
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-30
finished:
---

# e4a-deterministic-combine — spec for E4a deterministic combine (OME-1289)

## Intent

Write the spec set (PRDs, ERD, contracts, test plan) for epic OME-1289 (E4a · Method Support:
combine answers without a synthesizer, deterministically). The design is a generic operator
framework in the engine: one combine endpoint, an operator registry, and a typed CombineResult.
Extract, normalize, reduce, and select are operator plugins. The SDK Fusion synthesizer slot
accepts a reducer. This unit writes documents only. Code starts after the user approves the spec
and the plan.

## Planned changes

- `docs/spec/2026-09-30-e4a-deterministic-combine/00-overview.md`
- `docs/spec/2026-09-30-e4a-deterministic-combine/erd.md`
- `docs/spec/2026-09-30-e4a-deterministic-combine/prd/*.md`
- `docs/spec/2026-09-30-e4a-deterministic-combine/contracts.md`
- `docs/spec/2026-09-30-e4a-deterministic-combine/test-plan.md`
- this ledger

## Test plan

- Documents only. No code tests in this unit.
- Each PRD holds a TDD plan (RED first) for the later implementation units.

## Acceptance

- Each product decision traces to an interview answer (`ans:Qn`) or is marked as deferred.
- Each PRD can be built from without the chat transcript.
- The user approves the spec in plain words before the plan starts.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `docs/spec/2026-09-30-e4a-deterministic-combine/` — `00-overview.md`, `erd.md`,
  `contracts.md`, `test-plan.md`, and 11 PRDs in `prd/` (4 component PRDs, 7 flow PRDs). The plan
  `docs/plan/2026-09-30-e4a-deterministic-combine.md` (11 units, 7 waves, baseline results). This
  ledger. The spec was approved by the user on 2026-09-30. Code waits for the user's "start".
- **Commits:** none yet (waiting for spec review).
- **Gates:** documents only; no code gates.
- **Deviations:** The spec is a folder, not one file, because the prompt-planner layout needs
  several documents. The ERD diagram is inline Mermaid; the SVG + PNG export to `docs/diagrams/`
  is still to do. The interview moved samples() into P1 (ans:Q11) and the model-written merge
  field into P1 (ans:Q12). samples() is limited to seed-capable models (ans:Q13).
