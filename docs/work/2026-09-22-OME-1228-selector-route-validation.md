---
ticket: OME-1228
stack: screamingface-engine
status: done
started: 2026-09-22
finished: 2026-09-22
---

# OME-1228 — Preserve dataset-route validation through the selection wrapper

## Intent

Fix the reproduced PR #988 regression: its shared selector hides the dataset route in a
local-call context, allowing a missing route through registry installation. The user approved
this review fix on 2026-09-22. Continue in the existing issue worktree and PR.

## Planned changes

- Extend the OME-1228 spec and plan with the approved review correction.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/registry.py`: discover local
  context dependencies using the existing parser and respect runtime fallback boundaries.
- New `tests/unit/test_benchmark_context_routes.py`: registration and execution checks.
- Update the task mirror with validation results.

## Test plan

First reproduce missing selector dataset acceptance as a failing registration test. Cover a
valid registered dataset, nested context calls, quoted literals, unparseable prose, holdings
fallback and remote contexts. Preserve all prior tests. Run full Engine gates against ec6366c.

## Acceptance

Missing literal datasets fail installation; valid contexts remain accepted. No expression,
model input, grading, replay fingerprint, public API, or dependency changes. Engine gates pass.

## Outcome

- **Actual files:** as planned; production changes are confined to registry route discovery.
  No changes to generated protocols, replay fingerprints, model inputs or prior tests.
- **RED/GREEN:** missing selector data and nested local context routes first failed registration
  expectations. The independent review found leading/trailing empty slots; two additional failing
  tests drove normalization with URL4's own comma splitter. Final focused selection/foundation/
  protocol checks: 66 passed. Imported GSM8K with the optional Inspect dependencies: 14 passed.
- **Wisdom review:** reuse URL4 parsing rather than string-searching for route-looking text.
  Local contexts follow the runtime's holdings bypass and empty-slot rules; remote contexts
  belong to another node. No core-to-plugin imports, new dependencies or public API changes.
  Independent review confirmed the reproduced regression is fixed and found no false-positive
  rejection. The comma edge it identified is now covered and fixed.
- **Commits:** this iteration; message `fix(engine): validate dataset routes inside local contexts`.
- **Gates:** `UV_NO_SYNC=1 uv run .claude/scripts/run_gates.py screamingface-engine --base ec6366c35875bd8978bbfd1a26dd88653706548f` → ALL GATES GREEN with Inspect installed: append-only, lint, formatting, types, layering, full tests and coverage. No gate skipped.
- **Deviations:** continuing the existing issue worktree and PR, not creating a second branch.
  Gate baseline is the pre-fix head ec6366c, so this iteration proves tests are append-only
  independently of the previously approved test migrations already in PR #988.
