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
probe that can never fail tells Kubernetes that a pod with a dead NATS connection is ready to
serve, whatever the pod's actual state. OWNER DECISION: implement.

**Evidence boundary (review round 2, 2026-09-17).** This concern is established ENTIRELY by
reading `ops.py` and `deploy/helm/values.yaml`. Earlier drafts of this ledger, the PR body,
`values.yaml`, `ops.py` and two test module docstrings asserted as history that "every run
routed there was accepted and went nowhere" / the pod "accepted runs it could neither queue nor
stream". **No such incident was observed, reported or investigated, and nothing in this branch
demonstrates it.** It is also mechanically doubtful: with `runner=queue`, submission publishes
over NATS, so a dead connection makes the publish FAIL and surface as an error to the caller
rather than a silent accept. Every instance has been deleted or rewritten as a hypothetical. The
real, verifiable defect is narrower and sufficient: **the probe cannot fail.**

- `/readyz` asks the event stream whether it is reachable, and answers 503 when it is not. (An
  UNWIRED stream stayed 200 — see Deviation 3, which supersedes the first draft of this line.)
- The readiness contract lives in a new `screamingface_engine/readiness.py`: a
  `StreamNotReadyError` the adapter raises and a `stream_readiness()` helper the endpoint uses.
  ops.py stays free of any concrete adapter import and of `nats` exception types — the same
  port-boundary discipline `create_app_from_env` already applies with `getattr(job_runner,
  "aclose")`.
- `_JetStreamConnection.check_ready()` opens (or reuses) the connection — under a BOUND, see
  round 2's F2 — and reports a broker that is partitioned or closed. Deliberately NO
  `account_info()` RPC: a probe every 10s should not cost a broker round trip, and
  `Client.is_connected` already flips during a partition, which is the failure the probe exists
  to catch.
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

## Review round 2 (2026-09-17) — findings, judgements, and what changed

Eight findings were raised against the first round. Each was checked against the source before
acting; two were refuted with evidence rather than "fixed".

### F1 (HIGH, CONFIRMED) — `/readyz` leaked the NATS URL and the broker's own error text

`check_ready` raised `StreamNotReadyError(f"{self._url} is unreachable: {exc}")` and
`f"{self._url} is not connected"`, and `ops.readyz` rendered that string verbatim as the 503
body's `reason`. Verified reachable from outside the cluster: the ops router carries no auth
dependency, and `templates/httproute.yaml` routes a single `/` PathPrefix rule to the App, so
`/readyz` is served at the gateway and not only to the kubelet. `config.natsUrl` is free-form
operator input (`values.schema.json` types it only as a string) and `nats://user:pass@host:4222`
is the standard nats-py auth form — so the URL is a credential, and even without one it
discloses internal broker topology. Same leak class as OME-941.

**Fixed in two places, deliberately:**
- At the raiser: `StreamNotReadyError` now carries a documented CONTRACT — a short, FIXED,
  operator-facing literal naming the CLASS of failure and nothing else. The three production
  messages are `event stream broker is unreachable`, `event stream broker is not connected` and
  `event stream broker dial timed out`. The transport detail is chained as `__cause__`.
- At the boundary: `stream_readiness` logs the full reason and the chained exception at WARNING
  (server-side, where only the cluster reads it) and then caps the rendered reason at
  `MAX_REASON_CHARS` (120) and strips control characters. One adapter forgetting the contract
  must not become a leak, and a probe must not be an unbounded reflector.

### F2 (HIGH, CONFIRMED) — the probe could block indefinitely

`check_ready` awaited `self._jetstream()`, which dials (`nats.connect`) on the App's event loop
under `_connect_lock` with no timeout whenever `_js` is None or the cached client is closed —
i.e. exactly during the outage the probe exists for. nats-py retries `max_reconnect_attempts`
servers `reconnect_time_wait` apart before raising `NoServersError`, so one probe can park far
past `readinessProbe.timeoutSeconds: 5`. Starlette cannot cancel the handler when the kubelet
gives up, so the next probe at `periodSeconds: 10` queues behind it on the lock and pending
handlers accumulate for the whole outage — on the loop that pumps every WebSocket. The reviewer
is right that this is worse than the static literal it replaced.

**Fixed with two bounds, both load-bearing and both tested:**
- `READINESS_DIAL_TIMEOUT_S = 3.0` in the adapter bounds the dial. Cancelling it unwinds
  `async with self._connect_lock`, so the next probe gets its own budget rather than queueing.
- `READINESS_TIMEOUT_S = 4.0` in `stream_readiness` bounds the whole check at the boundary, for
  an adapter with no bound of its own.
- Both are pinned BELOW the chart's rendered `readinessProbe.timeoutSeconds` by a test that
  reads `values.yaml`, so raising either without raising the probe's timeout fails the suite.

### F3 (MEDIUM, CONFIRMED) — `test_readiness_never_blocks_on_a_broker_round_trip` was a tautology

Correct: it pre-set `_js` and `_nc`, so `_jetstream()` returned on the cached fast path and the
`asyncio.wait_for(..., timeout=0.5)` could never fire. It asserted in its name what it did not
test. **The prior test was NOT deleted or rewritten** (append-only); it still pins the cached
fast path, which is worth pinning. Three new tests cover the path it missed, all driving the
UNCACHED branch with `nats.connect` monkeypatched to a coroutine that never returns:
`test_a_hanging_dial_is_bounded_rather_than_parking_the_probe`,
`test_a_hanging_dial_does_not_hold_the_connect_lock_for_the_next_probe`, and
`test_an_adapter_that_never_returns_does_not_park_the_probe` at the boundary.

### F4 (MEDIUM, CONFIRMED as fact; fixed as DOCUMENTATION, not as code) — D7

**D7. `/readyz` reports on the App's event-stream consumer only, and now says so.** Verified in
`app.py::create_app_from_env`: `app.state.stream` is `build_stream_consumer(settings)` → a
`JetStreamConsumer`. The queue runner is a separate object with THREE separate NATS connections
of its own — `RunQueue`, `JetStreamPublisher` and `ControlClient`, all built in
`adapters/factory.py::build_job_runner` — and `/readyz` does not ask it. So a pod whose runner
connections are dead while the consumer's is live does still report ready. The reviewer is
right on the facts.

The overclaim was in the PROSE, not the code: `ops.py`, `jetstream.py` and the PR body all said
the probe covered "can neither publish a run onto the queue nor bridge its frames". The fix is
to narrow the claim, not to widen the probe, because widening it makes F5/D8 strictly worse —
it puts three more connections' failures in front of every endpoint this Service fronts. Every
docstring now states the scope exactly and names what is NOT probed.

### F5 (MEDIUM, CONFIRMED as a real trade) — D8, and it is OPEN for the owner

**D8. Broker-aware readiness on a single-Service, single-`/`-PathPrefix deployment is an
availability trade this branch makes VISIBLE but does not claim to have settled.**

The cost the first round never acknowledged: a TOTAL NATS outage empties the Service's endpoints
for every replica at once, so paths that need no broker at all — token mint, `/docs`, catalog
REST, artifact GETs — go 503 at the gateway. The PR body reasoned carefully about why liveness
must stay broker-blind and then said nothing about the symmetric readiness cost.

My reading of the trade, stated so the owner can overrule it cheaply:
- Readiness gating pays off in PARTIAL failure — this pod's client is wedged while its peers are
  fine, or a cold start that has not connected yet. Both are real and both are what the ticket
  targets.
- It pays NOTHING in TOTAL failure — with one shared NATS service, failure is usually total, and
  taking every replica out of rotation cannot route around an outage that has no healthy side.
  It only converts "run streaming degraded" into "whole API down".
- Which case dominates depends on the deployment's NATS topology, which is an operator fact I do
  not have.

**Not guessed at:** `failureThreshold` and the grace settings are left at the Kubernetes
defaults rather than tuned to a number nobody chose. The trade is written into `values.yaml`
next to the probe, where the operator making the call will read it. **If the owner wants
readiness to stay broker-blind, the change is small and local — delete the `stream_readiness`
call from `ops.readyz` and keep `/readyz` as an endpoint that exists; the leak and hang fixes
above stand either way.**

### F6 (MEDIUM, CONFIRMED and the most important item) — the invented incident narrative

Committed as permanent fact in five places: `ops.py`'s `readyz` docstring, `jetstream.py`'s
`check_ready` docstring, `values.yaml`, and the module docstrings of
`test_readiness_probe.py` and `test_chart_render_probe_paths.py` — plus the PR body. All of them
asserted that runs "were accepted and went nowhere" / the pod "accepted runs it could neither
queue nor stream".

**No evidence exists for this.** No incident was observed, reported or investigated; nothing in
the diff demonstrates the silent-acceptance path and no test reproduces it. It is also
mechanically doubtful, as C3's evidence boundary now records. Every instance is deleted or
rewritten to say only what was actually established by reading the code: **the probe could not
fail.** Each site now carries an explicit "no incident is claimed here" so the next reader
cannot re-inherit the story. (Editing a test MODULE DOCSTRING is not a test change: no test
function, assertion or fixture was touched.)

### F7 (LOW, PARTLY REFUTED) — `_CaplogBridge` semantics

The reviewer is right that `caplog.handler.handle(record)` applies filters but not levels, and
that forwarded records do not reach `caplog.get_records(phase)`. **Refuted as a live problem in
this branch:** `rg` over `apps/screamingface-engine/tests` finds ZERO uses of
`caplog.get_records(`, so the second divergence has no caller. And the bridge only fires while
`propagate` is False — i.e. only after a test has built an App — so a test that never builds one
is byte-for-byte unaffected. The whole suite passes in the gate run below, in the randomised
order the suite runs in. **Accepted as a naming point:** it is test infrastructure introduced by
a config-sweep ticket, and Deviation 4 already says so in full. No code change; recorded here
rather than silently agreed with.

### F8 (LOW, REFUTED) — `_QueueShapedRunner` in `test_active_runs_gauge.py`

The test asserts that a runner exposing no `active_count` produces no series, using a local
empty class. The reviewer's concern is that it pins a SHAPE rather than the production object,
so adding `active_count` to `QueueJobRunner` would start reporting an in-process count for a
fleet that executes elsewhere while the test stayed green.

**Refuted as written, for this test.** The gauge's contract IS the shape: `register_active_runs_metrics`
takes a `JobRunner` port and duck-types `active_count`, by design, because the App must not
import a concrete adapter (`check_layering.py` enforces this and would fail on an import of
`QueueJobRunner` from a metrics test). A test that named the concrete class would be testing the
wiring, not the gauge. The hazard the reviewer describes is real but belongs to whoever adds
`active_count` to `QueueJobRunner` — at which point the correct guard is a test that the QUEUE
runner's count is not exposed, which cannot be written today because the attribute does not
exist. Verified again on this branch: `QueueJobRunner` has no `active_count`. No change.

### Round-2 verification

- **New tests:** 12 added to `tests/unit/test_readiness_probe.py`, append-only. No prior test
  function, assertion or fixture was deleted, weakened or rewritten — including the first
  round's own. The tautological `test_readiness_never_blocks_on_a_broker_round_trip` was LEFT
  IN PLACE and supplemented rather than repaired.
- **Every new test was confirmed RED before its fix**, then green after.
- **Mutation testing, round 2: 11 planted, 11 killed**, run by a harness that plants each
  mutation, runs the file, and restores the source. The list, each with the count of tests that
  died: leak the URL back into the unreachable message (2); into the not-connected message (1);
  into the dial-timeout message (1); **drop the adapter's dial bound — the exact pre-fix
  unbounded await the reviewer named, which the old suite survived (3)**; raise the dial bound
  past the kubelet timeout (1); drop the boundary bound in `stream_readiness` (2); raise the
  boundary bound past the kubelet timeout (1); drop the length cap (1); drop the control-char
  scrub (1); drop the server-side log of the withheld detail (1); swallow the not-ready
  condition entirely (6).
- **No assertion reads `repr()`** of any object: the new tests walk `str(exc)`, decoded response
  bytes, parsed JSON members, `record.getMessage()`, parsed `values.yaml` and module constants.
