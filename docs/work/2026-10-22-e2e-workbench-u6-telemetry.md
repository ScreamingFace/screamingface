---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-22
finished:
---

# e2e-workbench-u6-telemetry — SDK events + OTel spans in the workbench (unit 6b)

## Intent

Capture every telemetry signal a workbench notebook run produces (SDK events, report and
accounting, the engine's and aigateway's OTLP spans) into its bundle and show it in the UI.
Plan: `docs/plan/2026-10-22-e2e-workbench-u6-telemetry.md`. 6a (engine) has its own ledger,
`2026-10-22-e2e-otel-local-runner.md`.

## Planned changes

- Task 2: `tests/e2e/workbench/otlp_receiver.py` + spec §3.6 (done, `fbccb08b0`).
- Task 3: both targets export to the receiver.
  - `tests/e2e/harness/_local_proc.py`: `telemetry_env(receiver_url, service=)` and
    `checked_telemetry()`, which refuses any name outside `OTEL_*`.
  - `harness/stack.py` (`EngineProcess(telemetry=)`, `replay_stack(engine_telemetry=)`) and
    `harness/cache_seeded.py` (`CacheSeededGateway(telemetry=)`): the telemetry goes through
    `clean_env`, and the harness's own variables win.
  - `workbench/targets.py`: `start_target(..., otlp_endpoint=)`. Replay gives the gateway
    `aigateway` and the engine `screamingface-engine`. Local gives the runtime's allowlisted
    env (`up`/`down`) `aigateway`, and the separate `EngineProcess` `screamingface-engine`.
  - `workbench/conftest.py`: a session `otlp_receiver` fixture writing `<out>/spans.jsonl`. It is
    a dependency of `live_target`, so it outlives the target's teardown, when the gateway's
    batch exporter flushes.
- Task 4: the notebook records SDK events, report and accounting; the verdict bundles spans.
  - `workbench/telemetry_recorder.py`: `EventRecorder(path)`, the `on_event` callback (one
    redacted JSON line per event, written whole and flushed; cap 20 000, then `dropped`; never
    raises into the SDK) and `finish(report)`, which writes `report.json`, `accounting.json`
    (by model and by stage, per candidate) and `recorder.json` (counts, per-file outcome).
  - `build_notebooks.py`: the `EVENTS_PATH` parameter (default `""`, records nothing); the
    evaluate cell builds the recorder only when it is set; the result cell calls
    `recorder.finish(report)` after its one marker. Notebook regenerated.
  - `runner.py`: the private kernelspec puts `tests/e2e` on the kernel's `PYTHONPATH`, so the
    notebook imports the recorder (and the one redactor) instead of inlining a copy.
  - `redaction.py`: `is_secret_name` (moved from `otlp_receiver.py`) and `redact_named_tree`,
    which masks the string value of a secret-NAMED key (`Log` attribute `x-api-key`).
  - `bundle.py`: `prepare_bundle` (dir before the run; clears a previous run's telemetry),
    `settled` (bounded wait for the last span batch), `write_telemetry` (exact-trace-id spans,
    cap 20 000 + `dropped`, `telemetry.json` with a note saying why a file is empty).
  - `verdict.py`: passes `EVENTS_PATH=<bundle>/events.jsonl`; `judge_notebook(...,
    spans_for=)`, fed `otlp_receiver.spans_for` by `test_notebooks.py`.
  - `harness/_local_proc.telemetry_env`: adds `OTEL_BSP_SCHEDULE_DELAY=200` (see Findings).
- Tasks 5–7: see the plan.

## Test plan

- Task 3: harness env contract (`tests/e2e/test_harness_telemetry_env.py`), target wiring
  (`workbench/test_targets.py`), lane fixture wiring (`workbench/test_lane_telemetry_wiring.py`),
  then the real replay lane.

## Findings

- **In-process gateway under `screamingface up` does install tracing.**
  `_runtime/server._build_apps` calls `aigateway.main.create_app`, which calls
  `_attach_log_filter` → `install_tracing(os.environ)`. The `_serve` background child is
  spawned with no `env=`, so it inherits the `up` allowlisted env, `OTEL_*` included. No 6a
  follow-up is needed. Caveat: the runtime's own in-process Engine (9108, unused by the
  workbench) shares that env, so its spans would report as `aigateway`.
- **Replay emits no `chat.completions {provider}` span.** Every model call is a cache hit, served
  before provider dispatch, so the gateway emits only its server span
  (`POST /v1/chat/completions`). The provider span appears only on a real dispatch (local, paid).
- **Gateway spans landed after bundle time (Task 4).** Both services batch spans with the SDK
  default 5 s delay. On the first Task 4 replay run the bundle held 35 engine spans and none of
  the gateway's; the session file got them ~2 s later. Fix: `OTEL_BSP_SCHEDULE_DELAY=200` in
  the workbench telemetry env (the SDK reads it in `BatchSpanProcessor.__init__`, 1.45.1) plus
  `bundle.settled` (1 s still window, 10 s cap) before copying.
- **Replay accounting is empty.** The replay report's cases carry no `operations`, so
  `CandidateResult.accounting` has no rows; `accounting.json` faithfully says so
  (`by_model: []`). Task 5 must render that as "no accounting", not zeros.
- **`InspectEngineProcess`** (`harness/inspect_stack.py`) overrides `start` and ignores
  `telemetry`. The workbench doesn't use it.

## Outcome (fill at the end — required before COMMIT)

- **Task 3 real replay lane (2026-10-22):** 407 passed, 2 skipped (`just` not on PATH);
  quickstart PASS, trace `e771df721361e7ff65fcd8d8c3391af7`. `spans.jsonl`: 46 spans, 39
  under that trace, including one `url4.run` (service `screamingface-engine`) and two gateway
  `POST /v1/chat/completions` server spans (service `aigateway`). The remaining spans, such as
  snapshot-upload admin calls, sit under other trace ids.
- **Task 4 real replay lane (2026-10-22):** 460 passed, 2 skipped (`just` not on PATH);
  quickstart PASS. Bundle: `events.jsonl` 59 events (34 span, 21 log, 2 usage, 1 started,
  1 terminated; 0 dropped/failed), `spans.jsonl` 39 spans (`url4.run` + 2 gateway
  `POST /v1/chat/completions` + 2 frozen-copy calls), `report.json` and `accounting.json`
  written. Package gates: ruff, format, pyright clean; 4706 passed, 39 skipped, cov 97.02%;
  `check_notebooks.py`, `check_distribution.py` exit 0.
- **Task 6 live telemetry (2026-10-22):** `GET /runs/{id}/telemetry` (SSE, `ui/live.py`) tails the
  run's session `spans.jsonl` and every `<target>/<notebook>/events.jsonl`; complete lines only,
  redacted again on read, chunk/line/row caps counted. Handles close on end, `aclose` and
  cancel; a real-uvicorn test checks the fd on `spans.jsonl` is released when the client
  disconnects (mutation: removing the close fails 4 tests). Real replay via the UI (port 9131):
  run PASS, stream gave 1 model call (`openrouter/microsoft/phi-4`, cache hit, 75.6 ms), 59
  events, 46 spans, 6 live `counts` frames, then `end`. Lane: 538 passed, 2 skipped (`just`).
  Not seen in a real browser (the shared Playwright browser was busy); the inline script was
  run in node against a DOM/EventSource stub.
