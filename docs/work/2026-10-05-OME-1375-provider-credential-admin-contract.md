---
ticket: OME-1375
stack: repo
status: done
started: 2026-10-05
finished: 2026-10-06
---

# OME-1375-provider-credential-admin-contract — formalize the D18 admin successor contract

## Intent

Record the owner-approved D18 decision: the pair-addressed `Connection` admin API that lets the
Admin UI list, attach/replace and delete a provider credential without a Profile name. Docs only;
the Gateway (G0 writer floor, G1 successor) and Admin UI landings are separate issues under
`OME-1138`.

## Planned changes

- Create `docs/spec/2026-10-02-provider-credential-admin-contract.md` (normative D18 contract).
- Create `docs/plan/2026-10-02-provider-credential-admin-contract.md` (sequence, evidence, tests).
- Create the `OME-1375` mirror `docs/tasks/2026-09-25-OME-1375-provider-credential-admin-contract.md`.
- Update `docs/spec/2026-09-09-OME-1138-converge-connections.md`: §3.5 admin successor bullet, §8
  status line and D18 row (decided; three legacy concurrency outcomes, not two).
- Update `docs/plan/2026-09-09-OME-1138-converge-connections.md`: D18 gate row.
- Create the landing mirrors `docs/tasks/2026-10-06-OME-1497-provider-credential-writer-floor-and-admin-api.md`
  and `docs/tasks/2026-10-06-OME-1498-admin-ui-connection-admin-api.md` (filed 2026-10-06 with owner
  authorization).

## Test plan

- Docs only: `uv run .claude/scripts/run_gates.py repo --base origin/main` (mirror/ledger status
  gate, loop parity, script tests).
- Every code reference in the spec/plan re-checked against `origin/main` `40214a746`.

## Acceptance

- The spec states the approved routes, DTO, ordered disposition, bridge, writer floor, errors,
  window and falsifiers, with the formalization decisions listed in its §9.
- The umbrella spec points to it instead of repeating the HTTP shape; D18 is no longer open.
- No runtime, test or production change in this unit. Linear changes only with owner authorization:
  landing issues `OME-1497` (Gateway) and `OME-1498` (UI) filed 2026-10-06 under `OME-1138`;
  `OME-1209` blocked by `OME-1498`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two landing mirrors (`OME-1497`, `OME-1498`) and the
  filing record in spec §10, plan §3.A.4 and the umbrella plan D18 row.
- **Commits:** one `docs(aigateway)` commit; see the PR (`Refs: OME-1375`).
- **Gates:** `run_gates.py repo --base origin/main` ALL GATES GREEN (append-only check, three script
  test suites, loop parity, mirror status).
- **Deviations:**
  - The shadow proof is OAuth identity (`identity_sub`), not the blob byte equality of the approved
    packet: an owner decision of 2026-10-05, recorded in spec §9.
  - Three formalization clarifications (refresh check-without-advance, row 6 leftover document, D14
    refinement) and one deferral (stopping new shadow writes), all in spec §9.
  - Linear, with owner authorization: `OME-1497` and `OME-1498` filed 2026-10-06; `OME-1209`
    blocked by `OME-1498`. Still pending owner authorization: the `OME-1375` description correction
    (three legacy outcomes) and the `OME-1333` disposition comment.
