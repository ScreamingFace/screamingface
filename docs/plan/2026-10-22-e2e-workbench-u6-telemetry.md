# E2E workbench · Unit 6 — telemetry in the UI: SDK events + real OTel spans, live

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every telemetry signal a notebook run produces is captured into its evidence bundle and
shown in the workbench UI, live while the run executes and in full afterwards:
- every SDK event (`Started`, `Span`, `Usage`, `Log`, `Terminated`);
- the report and its accounting;
- the real OpenTelemetry spans the engine (`url4.run` tree) and aigateway (server and
  `chat.completions` spans) export over OTLP.

**Architecture.** There are three capture paths, all redacted before they touch disk, and one view.
1. **SDK events.** The notebook passes an `on_event` recorder that appends each event as a JSON line
   to `events.jsonl` inside the bundle directory, live. The result cell also writes `report.json`
   (`Report.to_dict()`) and `accounting.json`.
2. **OTLP spans.** The workbench session runs a small loopback OTLP/HTTP receiver at `/v1/traces`.
   It decodes the protobuf with `opentelemetry-proto`, which the `runtime` extra already pulls in,
   and appends each span to `spans.jsonl`. Both targets point the engine and gateway at it through
   `OTEL_EXPORTER_OTLP_ENDPOINT`, added to their allowlisted environments. At bundle time the
   spans of the run's trace ids are copied into the bundle.
3. **The engine change, unit 6a.** The local in-process runner wraps each run's publisher in the
   existing `SpanRelay(publisher, load_span_sink(env), traceparent=…)`, exactly as
   `runner/main.py:724` does for Jobs. It's a pure passthrough when no endpoint is configured,
   which stays the default. Today the local engine exports nothing.
4. **The UI.** The bundle page gets a **Telemetry** section with four views: a span waterfall,
   usage and cost by model and by stage, a log stream with a severity filter, and per-case
   results. The run page tails `events.jsonl` and `spans.jsonl` over SSE, so model calls appear
   as they happen.

**Tech Stack:** Python 3.12, opentelemetry-proto (already transitive via the `runtime` extra;
promote it to an explicit dev dependency), stdlib `http.server` for the receiver, the existing
FastAPI UI, and inline SVG for the waterfall (no JS library).

**Spec:** `docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.3 and §3.5. This plan adds §3.6,
"Telemetry", in Task 1.
**Depends on:** units 2 and 4 (#1455 and the UI branch).

## Owner decisions (2026-10-22)
- **Capture both** the SDK events and the real OTel spans.
- **Live and after:** the run page streams telemetry live, and the bundle page shows the full
  picture.

## Landings (cross-cutting → two leaves under OME-1636)
- **6a `screamingface-engine`:** local in-process runs export their span tree when OTLP is
  configured.
- **6b `repo-dev-processes`:** the recorder, receiver, bundle files and UI views.

## Global Constraints
- **No new runtime dependency** in any shipped package. 6a reuses `tracing.loader.load_span_sink`
  and `SpanRelay`, keeping the lazy import so the engine's cold-start layering check
  (`check_layering.py`) stays green.
- **Export must never fail or slow a run.** That is ledger D4 of `tracing/otlp.py`. If the
  receiver is down, the run still passes; the Telemetry section then says "no spans received".
- **Redact everything before it is written:** events, spans (attributes and names), report and
  accounting. Use `workbench/redaction.py`.
- **Loopback only:** the receiver binds `127.0.0.1` on a free port, accepts only
  `POST /v1/traces` with `application/x-protobuf`, and caps the body at 16 MiB.
- **Bounded size:** at most 20 000 events and 20 000 spans per bundle. Anything dropped is
  counted and shown, never silently truncated.
- **Gates:** engine `uv run pytest`, ruff, pyright, `check_layering.py`. SDK package: the full
  gates. The real replay lane and the UI e2e test must pass, and spans must arrive on replay.

## Review Focus
1. **A run with no receiver**, or one returning 500, still passes, and its bundle says why there
   are no spans.
2. **No secrets in a span attribute or event body** reach `spans.jsonl`, `events.jsonl` or the UI.
   Test with a provider error message that contains a key.
3. **Spans of another run, or another notebook,** sharing the receiver never appear in this
   bundle. Selection is by exact trace id.
4. **Live tailing** of a file being appended never shows a half-written JSON line, and doesn't
   leak a file handle when the client disconnects.
5. **The waterfall** stays readable at 1 000+ spans: collapse siblings and paginate, without
   freezing the page.

---

### Task 1 (6a): local in-process runs export their span tree
- **Files:**
  - `apps/screamingface-engine/src/screamingface_engine/adapters/inprocess.py`: wrap the
    publisher each run uses in `SpanRelay(..., load_span_sink(env), traceparent=...)`, entered
    and exited around `lifecycle_run`.
  - Tests in `apps/screamingface-engine/tests/unit/test_inprocess_span_export.py`.
- **Test, written first:** inject a fake sink through the loader seam. A local run then emits a
  `url4.run` root plus at least one child span with `gen_ai.request.model`, all under the run's
  trace id. With no endpoint, no sink is loaded, the relay is a passthrough, and the frames are
  byte-identical. If the sink raises, the run still terminates `succeeded`.
- **Gates:** engine suite, `check_layering.py`.

### Task 2 (6b): spec §3.6 + OTLP receiver
- **Files:**
  - `tests/e2e/workbench/otlp_receiver.py` with the interface
    `OtlpReceiver(out: Path).start() -> str`, returning the endpoint URL, plus `.stop()` and
    `.spans_for(trace_ids) -> list[dict]`.
  - Tests in `test_otlp_receiver.py`, using a real `OTLPSpanExporter` pointed at it.
  - The spec addendum.
- **Spans as JSON:** `{trace_id, span_id, parent_span_id, name, kind, start_ns, end_ns,
  status, service, attributes}`, with attributes redacted.

### Task 3 (6b): targets export to the receiver
- **Files:**
  - `targets.py`: replay passes
    `OTEL_EXPORTER_OTLP_ENDPOINT` plus `OTEL_SERVICE_NAME`, per service, to `EngineProcess` and
    `CacheSeededGateway` through the `clean_env` extras. Local passes them into the allowlisted
    runtime environment and the `EngineProcess` environment.
  - Confirm that the in-process gateway (`screamingface up`) calls
    `install_tracing(os.environ)`. If it doesn't, record that as a 6a follow-up rather than
    changing the runtime here.
  - The conftest wiring for receiver start and stop.
- **Test:** the real replay lane writes `spans.jsonl` containing a `url4.run` span under the
  notebook's trace id, plus a gateway `chat.completions` span.

### Task 4 (6b): notebook records SDK events, report and accounting
- **Files:**
  - `build_notebooks.py`: a new `EVENTS_PATH` parameter, and an `on_event` recorder that appends
    redacted JSON lines with flush. It needs a dataclass encoder for `Decimal` and `datetime`.
    `report.json` and `accounting.json` are written in the result cell.
  - `verdict.py` passes `EVENTS_PATH=<bundle>/events.jsonl` and copies the spans in at bundle
    time.
  - Regenerate the notebook.
- **Tests:** a builder test that the recorder is present and the result cell is still the single
  marker cell. A runner-level test with a fake client that `events.jsonl` lines are valid JSON
  and redacted.

### Task 5 (6b): UI Telemetry section (bundle page)
- **Files:** `ui/telemetry.py`, a pure loader that returns `Telemetry(events, spans, report,
  accounting, dropped)`; `pages.py`; tests.
- **Views:**
  - a waterfall: inline SVG, grouped by service, with model, tokens, cache status, duration and
    error status;
  - a usage and cost table by model and by stage;
  - a log list with severity filter;
  - a cases table.
- **Rendering:** `None` shows as "unknown", never 0. Everything is HTML-escaped.

### Task 6 (6b): live telemetry on the run page
- **Files:**
  - `ui/runs.py` or `app.py`: an SSE endpoint `/runs/{id}/telemetry` that tails `events.jsonl`
    and the receiver's `spans.jsonl` for that run's out dir. It reads only complete lines and
    closes when the run ends.
  - The run page gets a live table of model calls (model, tokens, cache, duration) and a counter.
- **Tests:** a half-written-line test, a disconnect closes the handle, and the end of the run
  closes the stream.

### Task 7: real end-to-end + docs
- **Run:** the replay lane, and the UI e2e test asserting that the Telemetry section shows spans
  and events for the run. Then the paid local run once, recorded in the ledger.
- **Docs:** the README Telemetry section, and the ledger.

## Out of scope
- **The production SigNoz path.** Hosted spans already go to SigNoz, and cloud evidence is
  unit 3.
- **Metrics and OTel logs over OTLP.** The engine and gateway export spans only today. Logs keep
  coming from the log files.

## Done when
- 6a is merged to `main` as its own PR (`screamingface-engine` leaf), and 6b lands with the UI PR
  after #1455.
- In the UI, a replay run shows live model calls during the run, and afterwards a waterfall with
  `url4.run` and gateway spans, plus usage and cost, logs and cases. A paid local run does the
  same.
