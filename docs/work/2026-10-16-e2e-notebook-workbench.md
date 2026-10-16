---
ticket: OME-1636   # umbrella epic (Triage, scope review requested)
stack: screamingface
status: done
started: 2026-10-16
finished: 2026-10-16
---

# e2e-notebook-workbench — spec for a notebook-driven, target-switchable e2e workbench

## Intent

The Colab "try it in 10 minutes" notebook is our most complete end-to-end check, but it runs
by hand against two hard-wired targets and asserts almost nothing. This unit writes the spec
for a workbench where a coded pytest suite executes reviewable notebooks against any target
(replay, local, PR preview, hosted dev). Each run produces an evidence bundle that proves the
trace chain client → engine → runner → aigateway. A local web UI launches the same runner and
views the bundles. This unit is spec only, with no code.

## Planned changes

- `docs/spec/2026-10-16-e2e-notebook-workbench.md` (new)
- `docs/plan/2026-10-16-e2e-workbench-u1-client-pairing-and-token.md` (new)
- `docs/plan/2026-10-16-e2e-workbench-u2-core.md` (new)
- this ledger

## Test plan

- Spec only. Every repo anchor cited in the spec is checked to exist before commit.

## Acceptance

- The spec states the decisions locked with the owner on 2026-10-15/16: target × scenario
  matrix; notebooks driven by pytest; a local web UI (not Electron); auth = option A now plus
  option B for the UI.
- The spec names its open questions and a decomposition into implementable units.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** spec + ledger + plans for units 1 and 2
- **Commits:** docs(spec): e2e notebook workbench
- **Gates:** docs-only; every repo anchor in the spec checked to exist
- **Tracking:** epic OME-1636 (Triage, scope review requested). Unit 1 = OME-1637, PR #1438,
  which carries this spec. Unit 2 is not yet filed.
- **Deviations:** the workbench moves to `packages/screamingface/tests/e2e/workbench/` so it reuses the replay harness (spec §3 updated). Hosted defaults are now prod hosts (spec §1 updated). Owner decisions 2026-10-16: pairing raises; score bands are hand-set.
