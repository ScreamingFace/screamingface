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
- Tasks 4–7: see the plan.

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
- **`InspectEngineProcess`** (`harness/inspect_stack.py`) overrides `start` and ignores
  `telemetry`. The workbench doesn't use it.

## Outcome (fill at the end — required before COMMIT)

- **Task 3 real replay lane (2026-10-22):** 407 passed, 2 skipped (`just` not on PATH);
  quickstart PASS, trace `e771df721361e7ff65fcd8d8c3391af7`. `spans.jsonl`: 46 spans, 39
  under that trace, including one `url4.run` (service `screamingface-engine`) and two gateway
  `POST /v1/chat/completions` server spans (service `aigateway`). The remaining spans, such as
  snapshot-upload admin calls, sit under other trace ids.
