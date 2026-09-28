---
ticket: OME-1267 (filed at PR time — earlier commits say `Refs: none (owner decision RD4)`)
stack: screamingface-engine
status: done
started: 2026-09-22
finished: 2026-09-22
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

- **Actual files:** as planned, plus `world/node_tier/` split into 7 modules (`build.py` extra),
  `world/wire.py`, and new test files per batch. See each commit body.
- **Commits:** 7a558bb8, 7a9bb943 (B1); a03668aa, 43f6df89 (B2); c069e145, 1995f965 (B3);
  ea2cc20d, 083cccd6 (B4); b5795fcf, 5b1b6ef6 (B5); f0b2490d (B6); docs 2f045975, deb2ce49,
  95f9a31c, 935d2d96, 98ff89b9.
- **Gates:** final run on f0b2490d — ruff, ruff format, pyright, layering, pytest with coverage:
  ALL GATES GREEN (`--skip-append-only`: the append-only check flags the rubric-approved edits
  of branch-only tests, each listed in its commit body). Integration 37 passed. Chart:
  helm lint/template green (defaults, values-cloud, node+s3, node+s3+garage),
  verify_chart_wiring 159/159.
- **Reviews:** each batch had a design review and at most one feedback round; a final
  whole-branch regression review closed all nine headline findings and found no regression on
  the ensemble path.
- **Deviations:** FX-67 dropped; FX-68 via the run producer; §2.2a/§2.2b added after the B1
  review; B3 review items fixed in B4; B6 added for the final-review items. Follow-ups are in
  04-review-fixes.md §4 (oversize files, garage selectors, trace flags, url4 public read-side
  API, live NetworkPolicy check). Plan-record edits after 98ff89b9 are committed with the
  ledger renames.
