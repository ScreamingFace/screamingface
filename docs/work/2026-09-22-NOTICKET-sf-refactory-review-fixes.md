---
ticket: none (owner decision RD4 — commits on sf-refactory, no Linear issue)
stack: screamingface-engine
status: in_progress
started: 2026-09-22
finished:
---

# sf-refactory — fix round for the units 1–3 review findings

## Intent

Six reviews of the `sf-refactory` branch (units 1–3: shared world, request scope, config
sections, collision guard, node tier, sync surface, chart) found one critical chart bug, seven
high defects and a set of partial spec items. This round fixes them. The rubric is
`apps/screamingface-engine/docs/plans/04-review-fixes.md`.

## Planned changes

- B1 node tier: `world/node_tier.py` → `world/node_tier/` package, `world/wire.py`,
  `world/connector.py`, `request_scope.py`, `artifacts/signing.py` (FX-1..FX-23).
- B2 App side: `rest/forwarder.py`, `app.py`, `local.py`, `runner/main.py`,
  `runner/executor.py`, `logs.py`, `world/serving.py` (`NodeMountRoute`) (FX-30..FX-43).
- B3 world config and guard: `world/config.py`, `world/factory.py`, `world/serving.py`,
  `benchmarks/registry.py` (FX-50..FX-58).
- B4 unit 1 hardening: `request_scope.py`, `trace_scope.py`, `.claude/scripts/check_layering.py`,
  tests (FX-60..FX-71).
- B5 chart: `deploy/helm/**`, `.github/scripts/verify_chart_wiring.py`,
  `tests/unit/test_chart_render_node_tier.py`, chart README (FX-80..FX-90).
- Plan amendments: PRD-01 §6, PRD-03 §6, test-plan §4, contracts C1/C2/ladder.

## Test plan

- Each FX starts with a failing test (see 04-review-fixes.md §3), except items marked
  *docs* / *chart-render*.
- Baseline before the round: unit 3426 passed / 7 skipped; integration 37 passed; pyright 0;
  ruff clean; layering OK; chart wiring 131/131.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` green.
- Integration suite green; `helm lint` green (defaults and `values-cloud.yaml`).
- Design review per batch finds no unresolved Critical/High.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
