# OME-908 — Fair run scheduling, implementation plan

- **Spec:** `docs/spec/2026-08-26-OME-908-fair-run-scheduling.md`
- **Linear:** https://linear.app/openmined/issue/OME-908/fair-schedule-concurrent-engine-runs-so-one-large-benchmark-run-doesnt
- **Branch:** `OME-908-fair-run-scheduling`
- **Stack:** `screamingface-engine` (`sdlc-python`)
- **Precondition:** the design session approves the spec (decision points D0–D5). Nothing
  below starts before that approval.

## 0. Baseline and safety net

- Confirm the worktree branches from `origin/main`; run
  `uv run .claude/scripts/run_gates.py screamingface-engine` once to record the baseline.
- No test that passes today may be deleted. Every new behavior lands as a failing test first.

## 1. RED — the fair-share gate contract

New file `apps/screamingface-engine/tests/unit/test_fair_share_gate.py`. Tests use an
event-driven fake fetch (no sleeps, no wall-clock flakiness) against a fixed capacity:

1. Two runs contend; service counts converge near 1:1 within stated bounds.
2. A solo run reaches full capacity.
3. A waiter cancelled while queued is removed; its successor is granted on the next release.
   A waiter cancelled in the instant after its grant (the `set_result`-vs-`Task.cancel`
   race) returns the permit on unwind — no leak (added 2026-08-27 after PR review).
4. A fetch error and a fetch cancellation both release the permit (`finally`).
5. Run completion drops its queue entry and frees its permits before the next grant decision.
6. Capacity 1 degenerates to strict round-robin; capacity below 1 is refused at construction.

Expected: all fail (no `fair_share` module exists yet).

## 2. GREEN — the gate

New file `apps/screamingface-engine/src/screamingface_engine/runner/fair_share.py`:

- `FairShareGate(capacity: int)` — fewest-in-flight grant over per-run FIFO queues, ties by
  least-recently-served with the tie line ROTATING on every grant (a grant sends the run to
  the back) — equal-weight max-min fairness (amended 2026-08-26: the earlier
  "deficit-round-robin" named a different mechanism; no deficit counters exist; amended
  2026-08-27 after PR review: a fixed arrival tie-break starves a later run whenever an
  earlier run's wait queue never empties — the benchmark-backlog shape — so the tie must
  rotate); grant is a synchronous critical section; `release` is the only wakeup point;
  close cancels waiters; a waiter whose task is cancelled after the grant lands in its
  future returns the permit on unwind (a done future refuses `cancel()`, so the task
  defers the cancellation and resumes into `CancelledError` instead of taking ownership).
- `FairShareIOLayer(inner, gate, run_id)` — a URL4 `IOLayer` wrapper that acquires a permit
  per `fetch`/`fetch_ex` and forwards capability ports exactly like
  `url4.dag.node.BoundedIOLayer` does (bound only when the inner layer has them).

Run the Layer-1 gate tests to green. No other module imports these two yet.

## 3. RED — the env plumbing contract

Extend `apps/screamingface-engine/tests/unit/test_job_env_contract.py`,
`tests/unit/test_runner_job_lifecycle_settings.py`, and `tests/unit/test_inprocess_runner.py`:

1. `job_env.IO_CONCURRENCY = "URL4_CLOUD_IO_CONCURRENCY"` is defined and absent from
   `job_env.SECRET` (it is not a credential).
2. `build_executor(env, ...)` with the env set produces an executor whose `url4_run` call
   passes `concurrency=<value>`; with the env absent, the call shape matches today's (pin the
   kwarg absence, not a literal 32 — the URL4 default stays owned by URL4).
3. The local app passes a shared gate into every in-process run; the deployed factory path
   does not build one.
4. `Settings.runner_io_concurrency` default 4 and `Settings.local_io_capacity` default 32
   exist; invalid values (below 1) are refused at validation, mirroring
   `url4.dag.executor._validate_concurrency`.

Expected: all fail.

## 4. GREEN — the plumbing

- `src/screamingface_engine/job_env.py`: add `IO_CONCURRENCY`.
- `src/screamingface_engine/config.py`: add `runner_io_concurrency: int = 4` and
  `local_io_capacity: int = 32` (validated ≥ 1), each with the alias comment pattern the file
  already uses.
- `src/screamingface_engine/adapters/k8s.py`: in `_env(...)`, append the env entry
  UNCONDITIONALLY (amended 2026-08-26, implementation review: `runner_io_concurrency` is a
  required setting with default 4, so no "unset" branch exists — and an explicit entry on
  every Job beats a stale `envFrom` copy, the same invariant `EXTRA_MODELS` carries).
- `src/screamingface_engine/adapters/factory.py`: pass `runner_io_concurrency` into
  `K8sJobRunner`.
- `src/screamingface_engine/runner/main.py` (`build_executor`) and
  `runner/executor.py` (`Url4Executor`): read the env; thread an optional `io_concurrency`
  and an optional io-wrapper (the gate binding) into the executor. Amended 2026-08-26 — the
  `url4_run` kwarg is TRI-state: OMITTED when unconfigured (pre-OME-908 byte-identical),
  `concurrency=N` when the env carries a budget, and an EXPLICIT `concurrency=None` when the
  gate wraps the run's io (the gate replaces, not stacks under, URL4's per-run
  `BoundedIOLayer` — the two-state instruction here would have stacked it).
- `src/screamingface_engine/adapters/inprocess.py` (added 2026-08-26, implementation
  review): pop any ambient `URL4_CLOUD_IO_CONCURRENCY` from a local run's env — local's
  bound is the shared gate, never a static env, even one exported in an operator's shell.
- `src/screamingface_engine/local.py` (`create_local_app`): build one `FairShareGate`
  (capacity `local_io_capacity`), hand it to the runner factory's executor builds, and close
  it on app shutdown next to the existing shutdown hooks.

Layering note: `fair_share.py` lives under `runner/` (run-mode infrastructure, like
`connector.py`); `local.py` remains the one composition point that crosses the boundary, so
`check_layering.py` must stay green without exemption edits.

## 5. RED → GREEN — integration and the no-regression pin

- Extend `tests/integration/test_local_spine.py`: two concurrent runs against a slow fake
  gateway endpoint both progress and complete; per-run in-flight counts stay within the fair
  bounds the gate enforces.
- Add a solo-run pin to `tests/unit/test_inprocess_runner.py`: with one active run, the
  executor's dispatch ceiling equals the full gate capacity, and the recorded frame sequence
  for a fixed expression is unchanged.
- Add the k8s manifest assertion to the existing runner manifest test file: the env is
  present on every Job (the default-16 and override variants; amended 2026-08-26 — see §4:
  the write is unconditional).

Placement amendment (2026-08-26): the two-run interleave and the solo saturation pins live
in `tests/unit/test_runner_io_concurrency.py` — two real executors against one mock gateway
with parked requests — which exercises the same invariants without the spine harness; the
recorded-frame baseline pin was not implemented. Deviation recorded in the work ledger.

## 6. Observability slice (small, engine-only)

- Per-run counters on the wrapper: `fair_share_granted_total`, `fair_share_waiting`,
  `fair_share_in_flight`, keyed by run — exposed through `screamingface_engine.metrics`
  beside the existing catalog and reaper metrics. One test asserts the counters exist and
  move under contention. (Gateway-side slot-wait telemetry belongs to the companion ticket.)

## 7. Docs, tickets, and delivery

- README (engine) and the chart values comments: the new env and settings, the Layer 3 ops
  note (`timeout_s` guidance, openrouter override pointer, runner co-scheduling requirement).
- Commit the diagram `docs/diagrams/ome-908-fair-run-scheduling.svg` + `.png`.
- File the companion sub-ticket (gateway fair semaphore keyed by the existing identity
  header) for the owner to confirm in the session — cross-cutting rule: one epic, one
  sub-issue per app.
- Run `uv run .claude/scripts/run_gates.py screamingface-engine` from the repository root.
- Fill the ledger outcome, commit with `Refs: OME-908`, push, open the PR. Squash-merge only
  on green CI. No `--admin`.

## Safety notes

- Every step leaves the tree shippable: the env-absent path must behave byte-identically to
  main after every stage (pinned by the step-3 tests).
- The gate adds one `await` point per fetch. The wrapper must not wrap the inner layer's
  non-I/O capability declarations (route listing is not I/O — same rule `BoundedIOLayer`
  applies).
- Rollback (amended 2026-08-26, implementation review — the recipe below named knobs that do
  not exist: both settings are required ints and the gate has no skip path): deployed mode —
  set `config.runnerIoConcurrency: 32` in the chart; every Job then runs exactly its
  pre-OME-908 width. Local mode has no off-switch by design: `local_io_capacity` is always
  ≥ 1, a solo run's ceiling and speed are unchanged, and interleaving concurrent runs IS the
  feature — lower the capacity to shape local arrivals. No redeploy of URL4 or the gateway
  in either case.
- Original (kept for the record, superseded above): set `runner_io_concurrency` unset and
  `local_io_capacity` to the per-run default path (gate skipped when capacity is unset) —
  one settings change, no redeploy of URL4 or the gateway.
