---
id: OME-1130
linear_url: https://linear.app/openmined/issue/OME-1130
status: in_review
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed: null
---

# Export a run's span frames to OTLP

The core of Phase 2 (`OME-1129`). Phase 1 made one `trace_id` greppable across services; this
is what makes SigNoz's **trace view** stop being empty — a waterfall with per-span timing
instead of a log search.

Four things worth knowing before touching this area:

- **The input is the WIRE, not `url4.observe`.** The issue points at `NodeStarted`/
  `NodeFinished`, which are the runner's in-process observation seam and are never published.
  What a relay sees is `SpanEvent` carrying `SpanData`. Building on `url4.observe` also fails
  `test_only_engine_extensions_import_url4`, which confines the url4 ENGINE to Runner adapters
  while exempting `url4.streaming` as the shared wire contract.

- **The mount point in the issue does not exist.** "The engine control-plane relay, never the
  runner" presumes a subscription that sees all runs; `stream_for(topic)` creates ONE
  JetStream stream per run, and only `ws/bridge.py` subscribes — per attached client. Owner
  decision: a **publisher proxy in the worker**, which sees every frame of every run whether
  or not anyone is watching. This deliberately overrides the issue's "never the runner".

- **Timing is better than the issue assumed.** It warns that durations must come from envelope
  publish times and carry publish latency. `SpanData` carries its own `start`/`end`, captured
  in the runner when the observation event arrives (`runner/executor.py:358`), so a duration is
  the node's own. Only the synthetic root uses envelope times, where it is exact.

- **A stopped run is indistinguishable from a failed one in the CHILD spans.** `SpanData.status`
  is only `ok | error`; `cancelled` is collapsed before publication. `TerminatedData.status`
  keeps all four states, so the synthetic root is the only place that distinction survives.

Two costs recorded rather than discovered later:

- **Export is off unless an OTLP endpoint is configured**, and configured through OTel's own
  env contract (`OTEL_EXPORTER_OTLP_*`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`)
  rather than a vocabulary invented here. That makes `OME-1131` a chart-values job with no new
  credential scheme to design.
- **The OTel SDK is imported lazily.** It costs ~62 ms of a Job's ~227 ms import budget, which
  every run would otherwise pay for a feature most do not use. `check_layering.py` guards a
  Job's cold start against the engine's own modules and structurally cannot see a third-party
  dependency, so a subprocess test covers that direction.

Ledger: `docs/work/2026-09-10-OME-1130-frame-otlp-exporter.md`
