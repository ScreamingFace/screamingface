---
ticket: OME-1130
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1130 — Frame-to-OTLP exporter at the engine control-plane relay

## Intent

The core of Phase 2. Phase 1 made one `trace_id` greppable across services; this makes SigNoz's
**trace view** stop being empty — a waterfall with per-span timing instead of log search.

This is an adapter, not a rewrite. The frames already ARE a span tree — though NOT in the shape
the ticket describes (see D2/D6). One published `SpanEvent` carries a whole completed span, and
identity rides the ENVELOPE: `traceparent` carries trace+span, `tracestate` carries the parent as
`url4.parent=`. So the parent edge is **given, not inferred**, and duration and status come off
the payload.

## Design decisions

**D1 — the mapper is PURE and separate from the transport.** `frames -> span tree` is a total
function over recorded fixtures, unit-testable with no OTel, no network and no engine boot. The
OTLP exporter is a thin sink behind it. This is not tidiness: it is what lets the risky half
(transport, backpressure, credentials) change without re-testing the semantics, and it keeps
the OTel import confined to one module.

**D2 — ~~span timing is PUBLISH time~~ — WRONG, corrected after reading the wire.** The ticket
says durations must come from envelope publish times and warns they carry publish latency. They
do not. `SpanData` carries its own `start`/`end`, captured in the runner when the observation
event arrives (`runner/executor.py:358`), so a duration is the node's own, not a publish
artifact. It is still *observation* time rather than exact `resolve` boundaries — but the
publish-latency caveat the ticket asks to be written down does not apply, and writing it down
anyway would have taught every future reader something false.

Publish time IS used for exactly one span: the synthetic root (D7), whose start/end come from
the `Started`/`Terminated` envelopes. For the run as a whole that is not an approximation —
the run really did begin when it published `Started`.

**D3 — the OTel dependency is confined to `tracing/otlp.py`, and the mount is the RUN mode,
not serve mode.** D3 originally said "serve-mode adapter ONLY"; that was written before the
mount point was resolved (D6 → D9) and is now wrong about the half. What survives is the part
that matters: `packages/url4/tests/unit/test_import_isolation.py` forbids `opentelemetry`
anywhere reachable from `import url4`, checked in a **clean subprocess** so the claim has
teeth. The exporter lives in `screamingface_engine`, never in `url4`, so that holds by
construction. Within the engine the OTel import is confined to ONE module by the port/adapter
split in D8.

**D4 — export must never fail or slow a run.** The observation seam is explicitly synchronous
and non-blocking by contract (`observe.py`'s module docstring: the executor calls it inline from
its own coroutines). So the sink is fire-and-forget behind a bounded queue, and **drops on
backpressure rather than blocking**. A collector outage must degrade telemetry, never the run.

**D5 — export every span for now, and say so.** `url4/streaming/trace.py` hardcodes
`_SAMPLED = "01"`, so every run is nominally sampled and there is no sampling decision to
honour. Head sampling would need a policy nobody has set. Exporting everything is correct at
current volume and wrong at some larger one; the point at which it becomes wrong is a decision,
so it is recorded rather than silently deferred.

**D6 — the mount point is NOT the WS bridge.** `ws/bridge.py` subscribes per attached client, so
mounting there would export spans only for runs somebody happened to be watching — the exact
"absent because not exercised" ambiguity that cost a real diagnosis in `OME-940`. The exporter
needs a subscription that exists whether or not a client is attached.

Investigating that turned up a harder fact: **there is no control-plane subscription that sees
all runs.** `stream_for(topic)` creates ONE JetStream stream per run, so the ticket's stated
mount point does not exist to be mounted on. Raised as a fork; the owner chose a **publisher
proxy in the worker**, which deliberately overrides the ticket's "never the runner". D9 records
what that costs.

**D7 — the exporter emits a SYNTHETIC ROOT SPAN, and that is not fabrication.** The runner emits
one `SpanEvent` per *node*; there is no frame for the run itself. Without a root, every
top-level node becomes its own root and one run renders as N disconnected traces — and worse,
every `url4.parent=` reference and every gateway `traceparent` from Phase 1 points at a span id
that exists nowhere.

That id is not invented: `lifecycle._trace_fields` publishes run-level frames under
`format_traceparent(trace_id, root_span_id)`, so **the `Started` envelope states the root's
identity** and the `Terminated` envelope states when it ended. The exporter materialises a span
that the wire already asserts. This is the distinction the mapper's own invariant draws — never
mint an id, always honour one.

Bonus recovered: `TerminatedData.status` is `succeeded | failed | stopped | timed_out`, four
states, where `SpanData.status` is only `ok | error`. So the ROOT span can distinguish a
stopped run from a failed one even though its children cannot — which partially repairs the
`cancelled`-collapse limitation recorded on the ticket.

**D8 — port/adapter split, so OTel is importable from exactly one module.** `tracing/relay.py`
defines the `SpanSink` port and the transparent `EventPublisher` proxy; `tracing/otlp.py` is the
only module that imports `opentelemetry`. The composition root wires them. This is the repo's
mandated hexagonal shape, and concretely it is what lets the relay's whole behaviour — mapping,
root synthesis, never-fail-the-run — be tested with a fake sink and no OTel, no collector, no
network.

**D9 — the sink is OFF unless an endpoint is configured, and configured the STANDARD way.**
`sink_from_env` returns `None` when no OTLP endpoint env var is set, so every existing run,
every local run, and every test is unaffected by construction. When one IS set, the exporter and
the resource are built from OTel's own env contract (`OTEL_EXPORTER_OTLP_*`,
`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`) rather than a config vocabulary invented here.

That is a deliberate gift to `OME-1131`: its job becomes "set standard env vars in the chart",
with **no new credential scheme to design**, and the owner decision it must stop for shrinks to
"which endpoint, which auth header".

**D10 — flush on shutdown is MANDATORY, not a nicety.** The run process is short-lived (D9's
mount is the Job entrypoint). A `BatchSpanProcessor` with default behaviour drops whatever is
still queued when the process exits — which is the tail of *every* trace, including the root
span, which is by definition the last thing emitted. That failure mode looks like "tracing
works" while every run is missing its ending. The sink's shutdown therefore calls
`force_flush()` before `shutdown()`, and `SpanRelay` is a CONTEXT MANAGER so the composition
root drives it with `with` — a hand-written `finally` works exactly as well right up until
somebody edits that function, and this failure is silent.

**D11 — an UNFINISHED span is not exported, and is counted.** OTLP has no representation for
"still running": `end_time=None` encodes as epoch 0 and renders as a 56-year span, while
`end == start` states a 0 ms duration that is simply a lie. Both are worse than an absent span,
so an unfinished span is skipped and surfaced in the relay's counters. (In practice unreachable
— `_RunState._finish` emits one frame per *completed* span — but `SpanData.end` is `Optional`
on the wire, so the mapper must answer for it.)

**Supersedes:** emit-time export makes the tracing backend the durable evidence store, which
retires the design-only "Enclave" trace store the spec sketches (§6, F2). Stated here so that
design is not resurrected.

## Planned changes

- `src/screamingface_engine/tracing/span_tree.py` (new) — the pure mapper.
- `src/screamingface_engine/tracing/relay.py` (new) — the `SpanSink` port + publisher proxy.
- `src/screamingface_engine/tracing/otlp.py` (new) — the OTel adapter (transport half).
- `src/screamingface_engine/runner/main.py` — wire the relay into the run's publisher.
- `pyproject.toml` — OTel SDK + OTLP exporter, engine only.

## Test plan

RED first. The mapper's own tests are already green; these are the new halves.

**The relay (no OTel, fake sink):**
- Every frame passes through to the inner publisher unchanged — transparency is the property
  that makes this safe to mount on the run's only publisher.
- A `SpanEvent` reaches the sink as a mapped `Span`; a non-span frame does not.
- `Started` + `Terminated` produce the synthetic root, with the run's own root span id.
- An undecodable `traceparent` is counted and NOT sent (never fabricate).
- An unfinished span is counted and NOT sent (D11).
- **A sink that RAISES does not fail the publish** — D4, the invariant the whole design exists
  to protect.
- `close()` is driven even when the run raised.

**The OTLP adapter (OTel, no network):**
- `sink_from_env` returns `None` with no endpoint set — off by default (D9).
- A `Span` becomes a `ReadableSpan` whose ids are the hex parsed to ints, whose timestamps are
  ns, and whose parent context is the run's root when `is_root_child`.
- The sampled flag is set — `BatchSpanProcessor.on_end` silently DROPS an unsampled span, so
  this is the difference between working and silently exporting nothing.
- The `gen_ai.*` attributes survive as their OTel-conventional names.

## Acceptance

- The mapper is total over the wire types and preserves the tree.
- No OTel import is reachable from `import url4` (existing test still green).
- No OTel import outside `tracing/otlp.py` within the engine.
- A run with no endpoint configured behaves exactly as before.
- `run_gates.py screamingface-engine` green, `check_layering.py` included.

## Outcome

- **Actual files:**
  - `src/screamingface_engine/tracing/span_tree.py` — the pure mapper; gained `span_from_frame`
    (the streaming relay sees frames one at a time), `identity_of`, and an `attributes` bag.
  - `src/screamingface_engine/tracing/relay.py` (new) — the `SpanSink` port, `otlp_configured`,
    and `SpanRelay`, a transparent `EventPublisher` proxy.
  - `src/screamingface_engine/tracing/otlp.py` (new) — the OTel adapter; the ONLY module in the
    engine importing `opentelemetry`.
  - `src/screamingface_engine/tracing/__init__.py` — re-exports the port half only, with an
    AIDEV-NOTE against re-exporting the adapter (it would undo the lazy import).
  - `src/screamingface_engine/runner/main.py` — `span_sink()` + the `with SpanRelay(...)` wiring.
  - `pyproject.toml` / `uv.lock` — `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`.
  - Tests: `test_span_relay.py`, `test_otlp_sink.py`, `test_span_export_wiring.py` (new);
    `test_span_tree.py` unchanged — the mapper's contract held under the refactor.
  - Mirror: `docs/tasks/2026-09-10-OME-1130-frame-otlp-exporter.md`.

- **Gates:** `run_gates.py screamingface-engine` **ALL GREEN** — append-only check, ruff
  check/format, pyright, `check_layering.py`, and pytest with coverage. Full engine suite
  **2760 passed, 9 skipped**. `packages/url4` `test_import_isolation.py` still green (7 passed),
  which is what D3 rests on.

- **Verification beyond the gates:**
  - **Six mutations, six killed.** Each critical invariant was broken on purpose to confirm the
    test that guards it actually fails: the relay swallowing sink errors; the `SAMPLED` flag;
    reparenting a top-level node onto the root; refusing an unfinished span; the verbatim
    status reason; blank-endpoint-means-off. A green test that cannot fail is the defect this
    project keeps re-learning, so this is now routine rather than optional.
  - **The OTLP encoding was PROVED, not assumed.** A hand-built `ReadableSpan` was pushed
    through `encode_spans` before any of this was written, because "construct SDK spans by hand
    from foreign ids" is the one part of the design with no precedent in the repo.
  - **Cold start measured, not estimated:** 227 ms with the eager import, 201 ms without, and
    `import screamingface_engine.runner.main` now loads **0** `opentelemetry` modules.

- **Deviations:**
  - **`EventPublisher.close` already exists, is `async`, and is NOT abstract — pyright caught a
    real bug.** The relay's sink-shutdown method was called `close`, which silently overrode it
    with an incompatible sync signature. Nothing would have failed until someone did
    `await publisher.close()` on a wrapped publisher — at teardown, in production, on the path
    that only runs when something is already going wrong. Split into an async `close` that
    forwards to the transport and a sync `shutdown` that closes the sink, with a test for the
    distinction. Worth recording because `run_evidence.TerminalWatch` proxies the same port and
    does not forward `close` either — the same latent gap, not introduced here, not fixed here.
  - **The mount point overrides the ticket, by owner decision.** See D6.
  - **Three of the ticket's stated premises were wrong** (the observation seam, publish-time
    durations, the mount point) and one of its warnings did not apply. Corrected on the issue
    rather than implemented as written.
  - **Flush-on-shutdown is enforced by `with`, not by a `finally`.** D10's failure mode is
    silent — every trace merely loses its ending — so the context manager makes it structural.
  - **`SpanRelay` exposes `undecodable`/`unfinished` counters that nothing reads yet.** Kept
    because the relay must be able to say a trace is incomplete, and flagged rather than
    silently left. A future line in `_log_terminal` is the natural consumer.
  - **Local (`--local`) runs export nothing**, because they call `lifecycle.run` from the
    in-process adapter rather than through `runner/main`. That is the same split `run_evidence`
    hit and documented. In scope terms it is correct — Phase 2 targets the deployed trace view,
    and a local run has no collector — but it is a real asymmetry, not an oversight.
  - **Not covered by this unit:** `OME-1131` supplies the endpoint and credentials, without
    which every one of these paths is inert in production. Nothing here has yet exported a span
    to a real collector; the acceptance for that lives in `OME-1131`.
