---
ticket: OME-1027
stack: scoreboard
status: done
started: 2026-09-04
finished: 2026-09-04
---

# OME-1027 — Make the private-board rollback floor operational

## Intent

Prevent an emergency rollback from either publishing private submissions or destroying them
without a verified export. Replace mutable/ambiguous release identity with Helm revision plus image
digest evidence and provide the exact destructive operation the existing runbook only gestures at.

## Planned changes

- `docs/tasks/2026-09-04-OME-1027-rollback-floor.md` — Linear mirror and closure boundary.
- `docs/spec/2026-09-04-OME-1027-rollback-floor.md` — threat model and binding decisions.
- `docs/plan/2026-09-04-OME-1027-rollback-floor.md` — implementation sequence.
- `apps/scoreboard/src/scoreboard/check_rollback_safety.py` — semver becomes diagnostic only.
- `apps/scoreboard/src/scoreboard/purge_private_benchmark.py` — export-certified destructive CLI.
- `apps/scoreboard/src/scoreboard/scores/store.py` — explicit connection for transactional export.
- `apps/scoreboard/DEPLOYMENT.md` — executable release-floor and fallback procedure.
- `apps/scoreboard/tests/unit/test_check_rollback_safety.py` — corrected release identity contract.
- `apps/scoreboard/tests/unit/test_purge_private_benchmark.py` — new destructive-path coverage.

## Test plan

- Prove semver is labelled diagnostic and never described as the floor.
- Prove a matching export digest is necessary but insufficient without explicit confirmation.
- Prove mismatch, public board, unknown board, and baseline references refuse without mutation.
- Prove confirmation deletes exactly the exported private scores, their idempotency mappings, and
  the named benchmark while preserving neighbours.
- Prove any failed final deletion rolls the score deletion back.
- Run full Scoreboard gates including portal tests.

## Acceptance

- The runbook records and compares Helm revision, deployed image, and runtime image digest.
- Every destructive fallback command is executable and ordered fail-closed.
- No private data is deleted without a matching saved-export digest and explicit confirmation.
- The procedure requires `SAFE`, zero pods, and zero endpoint addresses before rollback.
- Full gates are green; operational production evidence remains an explicit closure requirement.

## Outcome

- **Actual files:** as planned. Added the export-verified purge CLI and its new unit suite; made
  the full-history reader transaction-aware; corrected the preflight's release-identity language;
  replaced the incomplete fallback with exact evidence, export, purge, quiescence, endpoint, and
  restoration commands; committed the task/spec/plan/ledger set.
- **Commits:** one conventional feature commit on `OME-1027-rollback-floor` (squash target; final
  merge sha will be recorded in Linear).
- **Gates:** `run_gates.py scoreboard --base origin/main --skip-append-only` ALL GREEN: ruff lint,
  ruff format, pyright, Python suite with coverage ≥80, and all three explicitly named Node portal
  suites. Direct full-suite run: 608 passed before the final two added purge cases; focused final
  safety run: 26 passed. The final gate includes all 610 Python tests.
- **Deviations:** the prior test asserting package semver was the rollback floor was corrected
  under the owner's explicit 2026-09-04 Confidence-Gate approval, so the append-only check was
  skipped and documented. No database model or migration changed. Production Helm revision/image
  evidence is intentionally not claimed: this machine has no Scoreboard cluster context, so
  Linear remains In Progress after the code PR until an operator records that evidence and runs
  the preflight in a production pod.
