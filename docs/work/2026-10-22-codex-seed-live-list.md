---
ticket: OME-1713
stack: screamingface-engine
status: done
started: 2026-10-22
finished: 2026-10-22
---

# codex-seed-live-list — Match the Engine's Codex models to the gateway's live list

## Intent

PR #1441 (OME-1634) switched aigateway's Codex models to the live list. The Engine's Codex seed
still declared the five retired ids, so `test_declared_models_match_aigateway.py` failed on every
Engine PR; main never ran it because that merge touched only aigateway. Bring the seed in line.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/models/seeds/codex.py`: the four live slugs, in aigateway's order.
- Prior-test edits (owner-approved, `.claude/test-change-approvals/OME-1713.json`): the guard's sample Codex id, the five retired ids out of the pre-OME-859 migration list, the audited totals 117 → 116 / 88 → 87.

## Test plan

- On main the guard fails 4 tests; after the seed change 2 remain (both name retired ids); after the approved edits all pass.
- Run: test_declared_models_match_aigateway.py, test_model_seeds.py, test_model_registry.py, test_executable_model_catalog.py, test_runner_config.py, test_aigateway_connector.py, test_web_search_routing.py; ruff + pyright on touched files.

## Acceptance

- The Engine's declared Codex ids equal aigateway's served ones; the model-guard and model-seed tests pass; no other provider's ids change.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger, the task mirror and the approvals manifest.
- **Commits:** see the PR.
- **Gates:** the 7 test files above: 275 passed; ruff and pyright clean on touched files; pre-push gates on push.
- **Deviations:** two older test files needed edits (the seed alone left 3 assertions on retired ids); owner-approved.
