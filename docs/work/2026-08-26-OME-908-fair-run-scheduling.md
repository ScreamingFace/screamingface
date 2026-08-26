---
ticket: OME-908
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-08-26
finished: 2026-08-26
---

# OME-908 — Fair scheduling of concurrent Engine runs

## Intent

One benchmark-scale run (cold DRACO: ~20k judge calls, one provider key, up to 32 in
flight) monopolizes the gateway's 4-slot per-provider FIFO queue, so concurrent runs
stall until it drains. This unit delivers the approved spec's Layer 1: engine-side
fair budgets in both modes, plus the Layer 3 ops documentation.

## Planned changes

- `runner/fair_share.py` (new) — `FairShareGate` + `FairShareIOLayer`
- `job_env.py` — `IO_CONCURRENCY` name + total `io_concurrency_from_env` reader
- `config.py` — `runner_io_concurrency=16`, `local_io_capacity=32` (validated ≥ 1)
- `adapters/k8s.py` + `adapters/factory.py` — budget onto every Job env
- `adapters/inprocess.py` — pop any ambient budget from a local run's env
- `runner/executor.py` — `io_wrap`/`io_concurrency` seams; derived `url4_run` kwargs
- `runner/main.py` — `build_executor(io_gate=…)` binding runs into the shared gate
- `local.py` — one gate per app, metrics registration, shutdown AFTER the runner
- `metrics.py` — `screamingface_engine_fair_share_*` collector
- Helm values/schema/configmap — `config.runnerIoConcurrency`
- Tests: `test_fair_share_gate.py`, `test_runner_io_concurrency.py` (new); three
  contract tests extended

## Test plan

- Gate invariants (14 tests): solo saturation, freed-permit-goes-to-the-waiter,
  strict alternation at capacity 1, immediate share reversion, queued-waiter
  cancellation, no leak on fetch error/cancel, capability-port forwarding.
- Plumbing (10 tests): env name is per-run; total reader; settings validation;
  kwarg omitted vs. 16 vs. explicit `None`; one shared local gate, closed after the
  runner; ambient env popped; two concurrent runs interleaving through one mock
  gateway (peak ≤ capacity, freed permit serves the other run).
- Contract extensions: Job env exact-set gains `IO_CONCURRENCY`; `_ALLOWED_RUNNER_IMPORTERS`
  gains `runner/fair_share.py`.

## Acceptance

- Both spec Layer-1 modes implemented; Layer 3 documented (README + chart).
- Full `run_gates.py screamingface-engine` green.
- Rollback is one setting: `runnerIoConcurrency: 32` restores pre-OME-908 exactly.

## Confidence-Gate decision (recorded 2026-08-26)

Two prior tests required in-place modification — both contract EXTENSIONS, both
approved by the owner in session after the gate halted:

1. `test_runner_job_env_isolation.py` — the Job-env exact-set gains
   `URL4_CLOUD_IO_CONCURRENCY` (unconditional write, same envFrom-staleness
   rationale as `EXTRA_MODELS`; dated comment per file precedent).
2. `test_url4_executor.py` — `_ALLOWED_RUNNER_IMPORTERS` gains
   `runner/fair_share.py` (an io-port adapter in `connector.py`'s sense).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `deploy/helm/values.yaml`, `values.schema.json`,
  `templates/configmap.yaml`, `README.md`, spec/plan/task/work/diagram docs.
- **Commits:** f31e701a (docs: spec + plan) and this commit (implementation) — `Refs: OME-908`
- **Gates:** ruff check/format clean · pyright 0 errors · check_layering OK ·
  append-only OK post-approval · pytest 2070+ passed (unit+integration), coverage ≥ 80
  (final line recorded in the PR run)
- **Deviations:** none from the spec. One discovered necessity: `FairShareIOLayer`
  forwards `default_route` (unlike URL4's `BoundedIOLayer`, which never needs to) —
  documented in-code.
