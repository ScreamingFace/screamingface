---
ticket: OME-1130
stack: screamingface-engine
status: in_progress
started: 2026-09-10
finished:
---

# OME-1130 — Frame-to-OTLP exporter at the engine control-plane relay

## Intent

The core of Phase 2. Phase 1 made one `trace_id` greppable across services; this makes SigNoz's
**trace view** stop being empty — a waterfall with per-span timing instead of log search.

This is an adapter, not a rewrite. The frames already ARE a span tree: `NodeStarted` carries
`span_id` and `parent_span_id`, so the parent edge is **given, not inferred**, and pairing with
`NodeFinished` by `span_id` yields duration and status.

## Design decisions

**D1 — the mapper is PURE and separate from the transport.** `frames -> span tree` is a total
function over recorded fixtures, unit-testable with no OTel, no network and no engine boot. The
OTLP exporter is a thin sink behind it. This is not tidiness: it is what lets the risky half
(transport, backpressure, credentials) change without re-testing the semantics, and it keeps
the OTel import confined to one module.

**D2 — span timing is PUBLISH time, and that is an approximation that must be written down.**
`_Sequencer.next()` stamps `time=datetime.now(UTC)` on every published envelope
(`url4/streaming/lifecycle.py:62`), so a span's start/end are its `NodeStarted`/`NodeFinished`
FRAME times, not true resolve boundaries. Durations therefore include publish latency.

Acceptable for a trace UI; **not** a basis for SLOs. Recording it here rather than leaving it
to be discovered by whoever first measures against it and finds their numbers slightly wrong.

**D3 — the OTel dependency lives in the engine's serve-mode adapter ONLY.**
`packages/url4/tests/unit/test_import_isolation.py` forbids `opentelemetry` anywhere reachable
from `import url4`, checked in a **clean subprocess** so the claim has teeth, and CI runs it
with and without the `url4[server]` extra. `check_layering.py` gates the engine additionally.
An exporter that imports OTel from url4 core or the runner fails CI by design.

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
needs a subscription that exists whether or not a client is attached. Resolving exactly where
that lives is the first task of the transport half.

**Supersedes:** emit-time export makes the tracing backend the durable evidence store, which
retires the design-only "Enclave" trace store the spec sketches (§6, F2). Stated here so that
design is not resurrected.

## Planned changes

- `src/screamingface_engine/tracing/span_tree.py` (new) — the pure mapper.
- `src/screamingface_engine/tracing/otlp.py` (new) — the OTel sink (transport half).
- `pyproject.toml` — OTel SDK + OTLP exporter, engine only.
- Tests over recorded frame fixtures.

## Test plan

RED first, over the pure mapper:

- Parent edges are preserved exactly — a nested run yields the same tree the frames describe.
- One trace per run; every span carries the run's `trace_id`.
- `NodeFinished.status` maps to span status: `ok`, `error`, `cancelled` distinctly.
- A `NodeStarted` with no matching `NodeFinished` (a run cut short) does not crash the mapper
  and is reported as unfinished rather than silently dropped.
- A `NodeFinished` with no `NodeStarted` is reported, not guessed at.
- Duration is derived from envelope times, and a span whose frames carry no time is not
  assigned a fabricated one.

## Acceptance

- The mapper is total over recorded fixtures and preserves the tree.
- No OTel import is reachable from `import url4` (existing test still green).
- `run_gates.py screamingface-engine` green, `check_layering.py` included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
