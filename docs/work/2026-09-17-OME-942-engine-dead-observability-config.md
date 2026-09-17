---
ticket: OME-942
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-942 — Sweep the engine's dead observability config

## Intent

Five loosely-related pieces of engine observability config are declared but wired to nothing,
so each one reads as a working control and is not. An operator who turns a knob that does
nothing is worse off than one who has no knob: the deployment looks instrumented while the
evidence it is supposed to produce never appears. This unit wires all five, in one PR as the
ticket asks, each kept a separate concern below.

The owner has DECIDED the two forks this ticket names: `/livez` + `/readyz` are IMPLEMENTED,
not deleted, and `InProcessJobRunner.active_count` is REGISTERED as a real gauge, not
de-documented.

## Concerns

### C1 — `URL4_CLOUD_LOG_LEVEL` is unreachable from a deployment

`logs.configure()` reads `URL4_CLOUD_LOG_LEVEL` (`logs.py:36`), but nothing in the chart sets
it, so no deployed pod can be turned to DEBUG — the one thing an operator wants during an
incident. Chart it as `config.logLevel` and render it to BOTH halves: the App's ConfigMap and
the runner pool's `-runner-env` ConfigMap. Both halves run `screamingface_engine` code through
`cli.main`, which calls `configure_logging()` for every mode — a level reaching only the App
would leave the worker pods (whose per-run log context OME-1069 built) permanently at INFO.

### C2 — `logs.configure()` is bound to `cli.main` only

`uvicorn.run()` installs handlers for the `uvicorn*` loggers only; the `screamingface_engine`
tree falls through to `logging.lastResort` at WARNING, which is the exact regression `logs.py`'s
docstring documents. Today only `cli.main` prevents it, so any other ASGI entry — `uvicorn
screamingface_engine.app:create_app_from_env`, an embedding process, a test harness — silently
loses every app INFO line. Call `logs.configure()` from `create_app`, which every ASGI entry
goes through. It is idempotent by construction (it marks its own handler), so `cli.main`'s call
followed by `create_app`'s installs one handler, not two.

### C3 — `/livez` and `/readyz` are static literals the chart never probes

Both probes hit `/healthz`; `/readyz` returns `{"status": "ready"}` unconditionally. A readiness
probe that can never fail tells Kubernetes a pod with a dead NATS connection is ready to serve —
the pod then accepts runs it cannot stream and cannot queue. OWNER DECISION: implement.

- `/readyz` asks the event stream whether it is reachable, and answers 503 when it is not or
  when no stream is wired at all.
- The readiness contract lives in a new `screamingface_engine/readiness.py`: a
  `StreamNotReadyError` the adapter raises and a `stream_readiness()` helper the endpoint uses.
  ops.py stays free of any concrete adapter import and of `nats` exception types — the same
  port-boundary discipline `create_app_from_env` already applies with `getattr(job_runner,
  "aclose")`.
- `_JetStreamConnection.check_ready()` opens (or reuses) the connection and reports a broker
  that is partitioned or closed. Deliberately NO `account_info()` RPC: a probe every 10s should
  not cost a broker round trip, and `Client.is_connected` already flips during a partition,
  which is the failure the probe exists to catch.
- The chart's `readinessProbe` moves to `/readyz`, and `livenessProbe` moves to `/livez` — the
  only thing "implement `/livez`" can mean, and the reason it exists as a separate endpoint from
  `/healthz` at all. `/healthz` is untouched and still served.

### C4 — the unused `pods/log` RBAC grant

Already gone: `deploy/helm/templates/role.yaml` was deleted wholesale in 4cdfa920 ("cut the
chart over to the worker pool and retire the Job adapter"), which took the Role, the RoleBinding
and the `pods/log` grant with it. Verified: no `pods/log`, no `kind: Role` and no `role.yaml`
anywhere in the tree. Nothing to do — recorded rather than invented.

### C5 — `InProcessJobRunner.active_count` claims to be a gauge and is not

Its docstring says "what `/metrics` would report"; no collector ever read it, so in-flight run
count — the admission gate's own input — was invisible to an operator. OWNER DECISION: register
it. A `_ActiveRunsCollector` alongside the existing queue/reaper collectors, registered from
`create_app`'s `_register_runner_metrics` through a getter, so a runner without an
`active_count` (the queue runner) simply yields no series rather than a misleading 0.

NOT done, per the ticket: no scrape endpoint is added to the run-mode Job. The gauge is served
by the App's existing `/metrics` only, so `check_layering.py` is unaffected.

## Planned changes

- `apps/screamingface-engine/deploy/helm/values.yaml` — `config.logLevel`; probe paths.
- `apps/screamingface-engine/deploy/helm/values.schema.json` — `config.logLevel` enum.
- `apps/screamingface-engine/deploy/helm/templates/configmap.yaml` — render `URL4_CLOUD_LOG_LEVEL`.
- `apps/screamingface-engine/deploy/helm/templates/configmap-runner-env.yaml` — same key.
- `apps/screamingface-engine/src/screamingface_engine/app.py` — `logs.configure()`; active-runs collector.
- `apps/screamingface-engine/src/screamingface_engine/readiness.py` — NEW: readiness contract.
- `apps/screamingface-engine/src/screamingface_engine/ops.py` — NATS-aware `/readyz`.
- `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` — `check_ready()`.
- `apps/screamingface-engine/src/screamingface_engine/adapters/inprocess.py` — docstring.
- `apps/screamingface-engine/src/screamingface_engine/metrics.py` — `_ActiveRunsCollector`.
- Tests (all NEW files; prior tests untouched):
  `tests/unit/test_chart_render_log_level.py`,
  `tests/unit/test_app_configures_logging.py`,
  `tests/unit/test_readiness_probe.py`,
  `tests/unit/test_active_runs_gauge.py`.

## Test plan

RED first, each confirmed failing for the right reason.

- C1: the default level is in `values.yaml`; the rendered App ConfigMap carries
  `URL4_CLOUD_LOG_LEVEL`; the rendered runner-env ConfigMap carries it too; a NON-default
  override (`DEBUG`) reaches BOTH halves — a default-valued assertion passes against a chart
  that renders only one half; `values.schema.json` refuses a level that is not a logging level.
- C2: after `create_app()`, the `screamingface_engine` logger owns the handler `logs.configure`
  installs and does not propagate; `URL4_CLOUD_LOG_LEVEL=DEBUG` in the environment is the level
  the app logger ends up at; a second `create_app()` does not stack a second handler.
- C3: `/readyz` is 200 + `{"status": "ready"}` for a stream that reports ready; 503 for a
  stream whose `check_ready` raises `StreamNotReadyError`; 503 when no stream is wired at all;
  200 for a stream with no `check_ready` at all (the in-process stream needs no broker).
  `_JetStreamConnection.check_ready` translates a partitioned client into `StreamNotReadyError`
  and a connect failure into the same, and passes for a connected one. Chart: the rendered
  `readinessProbe` targets `/readyz` and the `livenessProbe` targets `/livez`.
- C5: `/metrics` on an App whose runner reports 2 in-flight runs exposes
  `screamingface_engine_active_runs 2.0`; the value FOLLOWS the runner (a second scrape after
  the count changes reports the new number, not a captured one); a runner without
  `active_count`, and a `None` runner, expose no such series at all.

Assertion hygiene: every assertion walks real fields — parsed Prometheus samples, parsed YAML,
`logging` handler objects, response JSON. No assertion over `repr()` of an object.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine` green, coverage not lowered.
- `python3 .github/scripts/verify_chart_wiring.py` green (chart edits are gated by `charts.yml`).
- Chart assertions are made against the RENDERED manifest, never `helm lint` — lint reports
  success for a chart that cannot render.
- Every new behaviour survives a mutation of the production code that should break it.

## Outcome

- **Actual files:** as planned, plus three not foreseen:
  - `deploy/helm/README.md` — how to turn a deployment to DEBUG, and a table of what each probe
    asks and what its failure does. The ticket is about config an operator cannot reach; leaving
    the new knob undocumented would have reproduced the defect one level up.
  - `tests/conftest.py` — NEW. See Deviations; no prior test was modified.
  - `tests/unit/test_chart_render_probe_paths.py` — the chart half of C3, split into its own
    file so the async readiness tests can carry a module-level `asyncio` mark.
  - `src/screamingface_engine/app.py` also gained `_register_metrics`, a two-line extraction
    that keeps `create_app` under ruff's `PLR0915` statement ceiling after the
    `configure_logging()` call. The gate was not touched.
- **Commits:** see the PR; one commit, `Refs: OME-942`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine` — ALL GATES GREEN
  (append-only check, ruff check, ruff format, pyright, check_layering, pytest+coverage).
  3101 passed / 16 skipped; total coverage 93% against the 80% floor; `readiness.py` and
  `ops.py` at 100%, `metrics.py` at 98%. `python3 .github/scripts/verify_chart_wiring.py` —
  112/112 checks passed.
- **Mutation testing:** 13 mutations planted, 13 killed. Each named the tests that died:
  hardcoding the runner's log level (1); dropping the key from the App ConfigMap (2); relaxing
  the schema enum to any string (1); removing `configure_logging()` from `create_app` (6);
  swallowing the readiness reason (2); never asking the stream (3); checking `is_closed`
  instead of `is_connected` (1); narrowing the translated exception set to `NatsError` (2);
  reverting `/readyz` to a constant (2); pointing `readinessProbe` back at `/healthz` (1);
  pinning the gauge to 0.0 (2); removing the absent-runner guard (2); blanking the gauge's HELP
  text (1); caching the first reading instead of reading at scrape time (1).
  No assertion anywhere reads `repr()` of an object — every one walks parsed samples, parsed
  YAML, real `logging` handlers or response JSON.
- **Deviations:**
  1. **C4 was already done.** `templates/role.yaml` — Role, RoleBinding and the `pods/log`
     grant — was deleted wholesale in 4cdfa920 when the chart moved to the worker pool. No
     `pods/log`, no `kind: Role`, no `role.yaml` remains anywhere. Recorded, not invented.
  2. **`livenessProbe` moved to `/livez`**, which the ticket text does not name — it asks only
     that `readinessProbe` point at `/readyz`. The owner decision is IMPLEMENT rather than
     delete, and `/livez` has exactly one possible implementation: being the liveness probe's
     target. Leaving it unprobed would have left half of C3's dead surface in place.
  3. **`/readyz` treats an UNWIRED stream as ready**, not 503. The first draft failed it, which
     contradicted a prior test (`test_docs_ops.py::test_livez_and_readyz_return_200`, which
     builds `create_app()` with no stream). The prior test does not genuinely have to change:
     `create_app_from_env` always wires a stream, so the unwired shape is composition-time, not
     an outage, and the dead-probe defect — a WIRED stream whose broker is gone — is still
     fixed. MY test was changed to match the prior contract; the prior test is untouched.
  4. **`tests/conftest.py` is new test infrastructure, not a test change.** `create_app` now
     calls `logs.configure()`, which sets `propagate = False` on the process-global
     `screamingface_engine` logger — so the first test to build an App silently changed how
     every LATER test's records travelled, and 30 prior `caplog` tests failed depending on
     ORDER. They all pass in isolation, so this was leakage, not a behaviour regression. The
     conftest (a) saves and restores that logger around every test and (b) forwards records to
     `caplog` only while propagation is off, so no test sees a record twice. Not one prior test
     was deleted, weakened, skipped or edited; the production contract it isolates is asserted
     directly in `tests/unit/test_app_configures_logging.py`.
  5. **`URL4_CLOUD_LOG_LEVEL` is rendered to the runner pool as well as the App**, where the
     ticket names only "the configmap". Both halves run `screamingface_engine` through
     `cli.main`, which configures logging for every mode; a level reaching one half is the same
     class of half-working knob this ticket exists to remove.
- **Not done, deliberately:** no scrape endpoint was added to the run mode — the gauge is
  served by the App's existing `/metrics`, and `check_layering.py` is green.
- **Status:** DONE.
