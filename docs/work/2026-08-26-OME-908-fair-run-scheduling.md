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

## Outcome

- **Actual files:** as planned, plus `deploy/helm/values.yaml`, `values.schema.json`,
  `templates/configmap.yaml`, `README.md`, spec/plan/task/work/diagram docs.
- **Commits:** f31e701a (docs: spec + plan), 56596c6c (implementation), and the post-review
  documentation-alignment commit — all `Refs: OME-908`.
- **Gates:** ALL GREEN (`run_gates.py screamingface-engine`): append-only (approval below),
  ruff check/format, pyright, layering, pytest + coverage ≥ 80.
- **Deviations from the written spec/plan** (spec and plan amended 2026-08-26 to match;
  D0–D5 resolutions and per-criterion status live in the spec):
  1. The Job env is written UNCONDITIONALLY, not "when the setting is set" — the setting is
     required (default 16), and an explicit entry on every Job beats a stale `envFrom` copy
     (the `EXTRA_MODELS` invariant).
  2. Metrics are totals-only (`screamingface_engine_fair_share_*`): no per-run labels (topics
     are unbounded and mintable — cardinality discipline), no timeout/retry counters, no span
     events.
  3. The scheduler rule is fewest-in-flight/earliest-arrival (equal-weight max-min), not the
     "deficit-round-robin" the early drafts named.
  4. The `url4_run` kwarg is tri-state (omitted / `N` / explicit `None`); the plan's
     two-state instruction would have stacked `BoundedIOLayer` under the gate.
  5. The two-run interleave and solo saturation pins landed in
     `tests/unit/test_runner_io_concurrency.py` (real executors on a parking mock gateway)
     instead of extending the integration spine; the recorded-frame baseline pin was not
     implemented.
  6. The chart's co-scheduling note landed in the README first; the values.yaml runner-block
     comment was added post-review.
  Discovered during implementation: `FairShareIOLayer` forwards `default_route` (unlike
  URL4's `BoundedIOLayer`, which binds after ctx creation and never needs to) — documented
  in-code.

## Review response (2026-08-27, PR #750 CHANGES_REQUESTED by HupBaHa)

Both blocking findings were reproduced deterministically before fixing (repro scripts
kept out of the repo; the demanded regression tests are the in-repo artifacts):

1. **[P1] grant/cancel race leaked a permit — CONFIRMED.** `_pump` grants via
   `set_result` (schedules the waiter's resume); `Task.cancel()` landing before that
   resume cannot cancel the done future, sets `_must_cancel`, and the resume throws
   `CancelledError` at `await fut` — `granted` stays false, `_abandon` found nothing to
   remove, and `_active`/`_in_flight` were never reversed. Reproduced with capacity 1:
   the snapshot booked `in_flight=1` to the cancelled run and a fresh waiter
   deadlocked. The `_abandon` docstring's asyncio rationale was factually wrong (the
   module docstring already promised the correct behavior). Fix: `_abandon` now
   recognizes a granted future (done, not cancelled, no exception) and returns the
   permit through `release()` (guarded on `_closed`). Test added —
   `test_a_waiter_cancelled_after_grant_returns_the_permit` — failed pre-fix, passes
   post-fix.
2. **[P1] fixed arrival tie-break starved later runs — CONFIRMED with a refined
   mechanism.** `_arrival` stamps are (re)set when a run's wait queue is created, so a
   run whose queue never empties (unbroken fetch backlog — the benchmark shape this
   ticket protects) keeps the oldest stamp and wins every tie at equal holdings;
   reproduced 10/10 re-grants to run A, run B never served. (A demand gap re-creates
   the queue with a fresh stamp, which is why the existing capacity-1 test passed.)
   Fix: the tie line now rotates on every grant (the granted run's stamp is bumped),
   so no run wins two consecutive ties while an equal-holding competitor waits —
   capacity 1 under unbroken demand is strict round-robin, plan invariant 6. Test
   added — `test_unbroken_demand_from_more_runs_than_capacity_cannot_starve` (3 runs,
   capacity 1, replenished demand) — failed pre-fix, passes post-fix.

Also fixed: the wrong "impossible race" docstring on the queued-waiter cancellation
   test; plan/spec amended to the rotating tie-break and the grant-unwind permit return
   (the amendments above); PR title/body rewritten — they still described the PR as
   documentation-only. Full unit suite green: 2061 passed, 5 skipped.

## Companion ticket draft (Layer 2 — filing pending the owner)

The cross-cutting rule makes the gateway half its own sub-issue; Linear writes are
owner/MCP actions, so the text sits here until filed. When filed, link it from the spec's
Layer 2 and from OME-908.

- **Title:** Fair per-identity provider semaphore at the aigateway (OME-908 Layer 2)
- **App:** `apps/aigateway` (one sub-issue per app)
- **Problem:** the per-provider admission is a FIFO `asyncio.Semaphore`
  (`AIGW_PROVIDER_MAX_CONCURRENCY`, default 4, `core/concurrency.py`) with no caller class,
  so one wide run's continuously arriving calls starve a concurrent run even after
  OME-908's engine-side shaping (which only shapes arrivals, never the queue order).
- **Design:** replace the FIFO waiter list with a round-robin queue keyed by the caller
  identity header the gateway already receives on every engine call
  (`runner/connector.py` sends it); add per-class slot-wait telemetry (OME-886-adjacent).
  Exact work-conserving max-min at the true bottleneck; works for every engine replica; no
  contract change.
- **Refs:** `docs/spec/2026-08-26-OME-908-fair-run-scheduling.md` Layer 2; decision D4.
