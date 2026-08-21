---
ticket: OME-925
stack: screamingface-engine
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-925 — Observable benchmark asset preparation

## Intent

Close the review follow-ups from OME-875 without changing benchmark assets: preserve each
preparer's audit evidence, make expected build refusals readable, converge local and image
preparation on the deployment entrypoint, and retain network-heavy benchmark build layers in CI.

## Planned changes

- Preparation port, deployment result, shared expected exception, and orchestrator CLI.
- DRACO, IFEval, and HealthBench complete-bundle return values and exception inheritance.
- Deployment/CLI/static guard tests, local stack preparation, and benchmark-image CI caching.
- Task, spec, plan, work ledger, and draft-PR evidence.

## Test plan

- RED: summaries survive shared-bundle deduplication in stable order.
- RED: CLI prints one structured record per bundle and handles declared failures without traceback.
- RED: Docker and local preparation reject any family-specific entrypoint and derive the root.
- RED: CI names the complete benchmark image and declares an isolated persistent build cache.
- GREEN: focused deployment tests, then the complete `screamingface-engine` gate suite.

## Acceptance

- Build logs expose DRACO cases, IFEval cases/patched keys, and the HealthBench board split.
- Expected preparer refusals are concise and non-zero; unexpected exceptions remain visible.
- Image and local preparation use one registry-derived command.
- CI caches the benchmark preparation layer across runs.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the preparation port/deployment/orchestrator; all three family adapters;
  deployment, process-boundary, Docker, justfile and workflow contract tests; the local justfile;
  Engine image CI; and this unit's task/spec/plan/work records.
- **Commits:** the `fix(screamingface-engine): make benchmark asset preparation auditable`
  commit carrying this outcome (`Refs: OME-925`).
- **Gates:** official `run_gates.py screamingface-engine --skip-append-only` — ALL GATES
  GREEN (Ruff check/format, Pyright, layering, full pytest with coverage); 1,938 tests
  collected; focused deployment/preparer suite 42 passed; workflow YAML and justfile parsed.
- **Deviations:** append-only was skipped with owner approval because the ticket explicitly
  changes the inherited preparer return contract and strengthens its Dockerfile assertion.
  No inherited behavior or assertion was weakened. No other deviations.
