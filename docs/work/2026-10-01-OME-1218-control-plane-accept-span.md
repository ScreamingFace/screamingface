---
ticket: OME-1218
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# control-plane-accept-span — emit the run-submission server span; `url4.run` becomes its child

## Intent

The engine control plane emits no span of its own: `GET /` adopts the inbound `traceparent`
and forwards it verbatim, so accept + validate + enqueue + queue wait are invisible, and a run
submitted with no inbound context has `url4.run` as an orphan root. Owner decision (Linear
comment, 2026-10-01): **option 1 — `url4.run` becomes a CHILD of the control-plane accept span.**
The control plane forwards ITS OWN span id to the run, so one run is one trace with one root and
queue wait is the gap between the end of the accept span and the start of `url4.run`. Same
principle as `OME-1185` (#974): every hop names the span that is actually current, never an
ancestor further up.

## Source read (before design)

- `tracing/otlp.py` — `OtlpSpanSink.emit` hands a hand-built `ReadableSpan` to a
  `BatchSpanProcessor` (non-blocking, drops on overload); `close()` flushes with a 5 s bound.
  Ids are never minted by the SDK — they are supplied. The only module importing OTel.
- `tracing/relay.py` — `SpanRelay` emits `url4.run` from the `Started` frame's identity with
  `parent_span_id=None`, always.
- `url4.streaming.lifecycle.run` — adopts the inbound TRACE id, MINTS a fresh root span id and
  DISCARDS the inbound parent-id. So the relay cannot learn the parent from the wire: it must be
  handed the traceparent the run was given.
- `trace_scope.py` — run-scoped trace for outbound calls (`OME-1119`/`OME-1185`); untouched.
- `rest/routes.py::start_run` — `valid_traceparent(inbound)` → `_schedule(traceparent=…)` →
  `JobRunner.schedule`.
- Queue path: `runner_queue.py` renders `valid_traceparent(tp)` into `job_env.TRACEPARENT`
  (`URL4_CLOUD_TRACEPARENT`) in the queued run's env; the worker forks the run with it;
  `runner/main.py::_run_process` reads it and passes it to `lifecycle.run`.

## Design

- **D1 — `tracing/accept.py` (new, pure: stdlib + `span_tree.Span` + `url4.streaming.trace`).**
  `AcceptSpan.open(sink, inbound_traceparent, topic)`: trace id = the inbound one when valid,
  else minted; span id minted; parent = the inbound parent-id, or none. `.traceparent` renders
  `00-<trace>-<accept span>-01` — what the run is handed. `.scheduled()` / `.refused(status)`
  end it once (idempotent) and emit through the `SpanSink` PORT — never raises (a telemetry
  fault must not fail a submission, same invariant as the relay). Name `url4.accept`, kind
  `server`, attrs `http.request.method=GET`, `http.route=/`, `url4.topic`,
  `url4.accept.outcome`, plus `http.response.status_code` on refusal. 5xx refusal → error
  status; 4xx → ok (OTel HTTP server semconv: a client error is not a server error).
- **D2 — the span covers validate + enqueue only.** Opened at handler entry (after JWT
  verification, which is a dependency), ended right after `_schedule` returns — BEFORE the sync
  hold. The sync wait is not accept latency; including it would hide the queue-wait gap the
  ticket asks for.
- **D3 — `routes.py`**: a context manager wraps the handler body; a `ProblemException` ends the
  span `refused(<status>)`, any other exception `refused(500)`, both re-raised. The forwarded
  traceparent is the accept span's when one is open, else the inbound one (today's behaviour).
- **D4 — off by construction.** `app.state.span_sink` is `None` unless the deployment configured
  an OTLP endpoint; then no span is opened and the inbound traceparent is forwarded unchanged,
  exactly as today. Forwarding a self-minted parent that nobody exports would dangle.
- **D5 — wiring.** `create_app(span_sink=…)` DI seam; `create_app_from_env` builds it from env
  through a lazy-importing loader in `app.py` (the OTel SDK is imported only when configured;
  never on a Job's import graph). Closed on shutdown off the event loop (`asyncio.to_thread`,
  since `close()` may block up to its 5 s bound).
- **D6 — `relay.py`**: `SpanRelay(inner, sink, *, traceparent=None)` — the traceparent the run
  was handed. `url4.run`'s parent = its parent-id when its trace id equals the run's own (never
  a parent in another trace). Default `None` keeps every existing caller's behaviour.
- **D7 — `runner/main.py`**: one keyword on the one `SpanRelay(...)` construction
  (`traceparent=traceparent`). Unavoidable: it is the only place the relay is built and the
  only place that knows what the run was handed. Kept to that single line because `OME-946`
  is editing this file in parallel.
- **D8 — probes.** No probe span exists by construction: the span is opened by the submission
  handler alone, not by a route-wide middleware. Mirroring `aigateway/span_exclusion.py` now
  would be an exclusion list guarding routes that emit nothing (dead code). Pinned by a test that
  drives the probe/metrics routes with a sink installed and asserts zero spans.

## Out of scope — later step (recorded per owner instruction)

- Server spans for the other control-plane routes: catalog, artifacts, token mint (`POST
  /token`), `DELETE /`, and the mount routes' direct runs. Generalising to a route-wide server
  span is the point at which probe exclusion becomes real code — mirror
  `aigateway/span_exclusion.py` then (apps may not import each other; it is written liftable).
- Consolidating `runner.main.span_sink` and the control plane's loader into one shared lazy
  loader (needs a `runner/main.py` edit; deferred to avoid colliding with `OME-946`).

## Planned changes

- new `apps/screamingface-engine/src/screamingface_engine/tracing/accept.py`
- `tracing/relay.py` (D6), `rest/routes.py` (D3), `app.py` (D5), `runner/main.py` (D7, one line)
- new tests: `tests/unit/test_accept_span.py`, `tests/unit/test_accept_span_route.py`,
  `tests/unit/test_span_relay_parent.py`

## Test plan

- AcceptSpan: no inbound → fresh trace, parentless, forwarded traceparent names the accept
  span; inbound → same trace, parent = inbound span; malformed inbound → treated as none;
  ends once; a raising sink never propagates; 5xx vs 4xx status; kind server, attrs.
- Route: with a sink, the run is scheduled under the accept span's traceparent; accept span
  is a root without inbound, a child with inbound; refusals (409, 400) emit a refused span;
  sync path ends the span before the hold; without a sink the inbound is forwarded verbatim;
  probe/metrics routes emit nothing.
- Relay: `url4.run` parent = the handed traceparent's span id; mismatched trace → no parent;
  no traceparent → parentless (existing behaviour).
- End to end: accept span → forwarded → `lifecycle.run` → relay: one trace id, `url4.run`'s
  parent == accept span id, accept span is the trace's only root.
- Wiring: loader returns None unconfigured, a sink when configured, None when the exporter
  config explodes; shutdown closes the sink; importing `runner.main` still loads no OTel.

## Acceptance

- A run submitted with no inbound traceparent yields one trace whose first span is
  `url4.accept`, with `url4.run` its child; with an inbound traceparent, the accept span is a
  child of it. Probes emit no span. `run_gates.py screamingface-engine` green incl.
  `check_layering.py`. No prior test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — new `tracing/accept.py`; `tracing/relay.py`, `rest/routes.py`,
  `app.py`, `runner/main.py` (one keyword); new tests `test_accept_span.py`,
  `test_accept_span_route.py`, `test_span_relay_parent.py`, `test_accept_span_wiring.py`
  (35 tests). Mirror `docs/tasks/2026-09-17-OME-1218-control-plane-accept-span.md`.
- **Commits:** the single `feat(engine)` commit on this branch (see the PR).
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN (append-only vs HEAD, ruff
  check, ruff format, pyright 0 errors, check_layering.py, pytest + coverage ≥80).
  `check_mirror_status.py` exit 0. No prior test edited.
- **Deviations:**
  - `runner/main.py` touched (one keyword, D7) despite the instruction to avoid it while
    `OME-946` runs in parallel: it is the only construction site of the relay and the only place
    that knows the handed traceparent; a trivial merge if both land.
  - Probe exclusion is STRUCTURAL (D8), not a mirror of `aigateway/span_exclusion.py`: no
    route-wide server span exists, so an exclusion list would guard nothing. Mirror it in the
    later step that adds spans to other routes.
  - The control-plane sink loader duplicates `runner.main.span_sink` (layering forbids the
    import; consolidation deferred with the main.py edit).
  - A submission cancelled before enqueue (client gone mid-validation) emits no accept span.
  - `app.py` was already >450 lines; it grew by ~45.
