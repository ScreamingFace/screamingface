---
ticket: OME-1537
stack: aigateway
status: done
started: 2026-10-16
finished: 2026-10-16
---

# input-modalities — expose each model's input modalities on /v1/models

## Intent

Every `/v1/models` row reports which inputs the model takes (`text`/`image`/`pdf`) so the
engine can refuse a blind model before spending money (epic OME-1529, item 4 of OME-1271).
Unknown is `["text"]`, never vision. Spec: `docs/spec/2026-10-16-input-modalities.md`.

## Planned changes

- `apps/aigateway/src/aigateway/core/input_modalities.py` (new)
- `core/plugin_base/_ports.py` (ModelEntry evidence field), `_contract.py` (hook)
- `core/model_capabilities.py` (row field)
- `plugins/openrouter_provider/live_models.py`, `plugin.py`
- `plugins/huggingface_provider/discovery.py`, `plugin.py`
- `plugins/ollama_provider/discovery.py`, `plugin.py`
- `plugins/{anthropic,antigravity,gemini,codex,openai}_provider/plugin.py` (hook override only)
- tests under `apps/aigateway/tests/unit/` (new files only)

## Test plan

- normalize: unknown values dropped, text forced, canonical order, empty -> text.
- row contract: every row has `input_modalities`; default plugin -> `["text"]`; evidence carried.
- OpenRouter parser: file -> pdf, audio/video dropped, missing/malformed architecture -> absent.
- HF parser: per-id modalities; listing enrichment; catalogue failure propagates.
- Ollama: vision -> image, never pdf; `/api/show` failure -> text.
- Declared tables per provider, including an unknown family -> text.

## Acceptance

- Gates green; live `/v1/models` on port 9122 shows the expected modalities for the e2e set.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `plugins/huggingface_provider/settings.py` (opt-in flag).
  New tests: `tests/unit/core/test_input_modalities.py`,
  `tests/unit/openrouter/test_openrouter_input_modalities.py`,
  `tests/unit/huggingface/test_huggingface_input_modalities.py`,
  `tests/unit/ollama/test_ollama_input_modalities.py`, `tests/unit/test_declared_input_modalities.py`.
- **Commits:** `ba1ae75c9` feat(aigateway): expose each model's input modalities on /v1/models
- **Merged:** squash-merged as `2406ccd5a` (#1451) on 2026-10-22.
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN (append-only, ruff, format, pyright,
  no-enterprise, pytest + coverage >= 80; 6284 tests collected).
- **Live e2e (port 9122, copied DB, no Codex chat):** 415 rows, all carry the field, none out of
  contract. openrouter/google/gemini-2.5-flash text,image,pdf; openrouter/mistralai/mistral-nemo
  text; ollama/qwen2.5vl:3b text,image; ollama/qwen3:14b text; anthropic/claude-haiku-4-5 and
  antigravity/gemini-3-flash text,image,pdf; HF (opt-in on) gemma-3-4b-it text,image. Chat smoke:
  anthropic + antigravity read PNG and PDF, ollama reads PNG and misses the PDF (consistent with
  no `pdf`); the runner's openrouter calls 404'd `profile_not_found` (profile name `default`
  absent in the DB copy — harness, not this change).
- **Deviations:** (1) HF listing source is opt-in (`AIGW_HUGGINGFACE_LIVE_MODALITIES`, default
  off): HF is always loaded, so default-on would dial the router on every cold listing and
  trip the suite's no-egress guard in every prior `/v1/models` route test. Off -> HF rows are
  text-only. (2) OpenAI direct got a declared table too (the ticket names it; the dispatch brief
  did not). (3) Admitted OpenRouter models report text-only (no evidence threaded through
  admission).

## Review round 1 (HupBaHa 2026-10-20T15:50Z) — outcome

- **Fixed (tests first, new files only):**
  - F4 family boundaries: `core/input_modalities.py` `matches_family` — a family key matches only
    as the whole id or followed by `- . : @ / _` (`gpt-50`, `o30`, `o40`, `gpt-4oo`, `gpt-4.10` ->
    text). Anthropic classifies `litellm_params["model"]` (the routed target), not the alias.
    Tests: `tests/unit/test_declared_input_modalities_boundaries.py`.
  - F3 HF envelope: `discover_router_input_modalities` raises `DiscoveryError("malformed_json")`
    for a 200 that is not `{"data": [...]}`; the catalog keeps the last-good snapshot. Parser
    leniency kept for per-row fields (so the existing `test_parser_tolerates_a_non_catalogue`
    still holds unchanged). Tests: `tests/unit/huggingface/test_huggingface_input_modalities_envelope.py`.
  - F2 (bounds half) + F1 (single-flight half): `/api/show` is streamed under a 1 MB cap
    (`SHOW_MAX_BYTES`, reading stops at the cap), nested-JSON `RecursionError` -> unknown, and
    concurrent cold lookups of one (host, model) share one call. Tests:
    `tests/unit/ollama/test_ollama_show_bounds.py`.
  - Note: Ollama PDF wording in `ollama_provider/discovery.py` + spec no longer claims the gateway
    already refuses PDFs (that lands with #1447).
- **Not changed — needs owner decision:** F1 (probes still sync on the event loop) and the
  kill-switch half of F2. The clean fix moves `/api/show` probes into an Ollama
  `model_discovery_source` / async `discover_live_models` (ModelCatalog: off-loop, single-flight,
  last-good, `None` under `AIGW_DISCOVERY_ENABLED=false`) with `register_models()` returning
  probe-free seeds. That breaks this PR's `test_rows_publish_ollama_vision_as_image_only`
  (asserts `register_models()` carries `/api/show` evidence) and needs a POST-capable bounded
  transport (core `DiscoveryHttpClient` is GET-only) — a test change + port decision.
- **Not changed:** `/v1/models` OpenAPI stays a generic object (pre-existing route schema; out of
  this unit's scope — candidate follow-up).
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN.
- **Deviations:** none beyond the owner-decision items above.

## Review round 2 (owner decision 2026-10-21) — outcome

- **F1 + F2 kill switch, fixed (tests first):** `/api/show` probes moved off `register_models()`
  (now probe-free seeds) into an async Ollama `model_discovery_source` / `discover_live_models`
  run by the `ModelCatalog`: off-loop, single-flight per provider, last-good on failure, and
  absent under `AIGW_DISCOVERY_ENABLED=false` (no catalog). Round bounds:
  `OLLAMA_SHOW_CONCURRENCY = 4`, `OLLAMA_SHOW_DEADLINE_S = 5.0` for the whole round, each body
  `SHOW_MAX_BYTES` (1 MB) under the transport's total deadline; any failed probe fails the round
  (all-or-nothing) so a partial text-only listing is never cached as fresh. Successful per-model
  answers are memoized 60 s so the 10 s listing TTL does not re-probe unchanged models.
- **Port:** a bounded POST for the core transport — `DiscoveryPostClient` (runtime-checkable
  Protocol, core) + `HttpxDiscoveryClient.post` (same envelope as `get`: no redirects, identity
  encoding, byte cap counted before retained, total deadline, sanitized errors). Plugin narrows
  with `isinstance`; a GET-only transport -> `DiscoveryError("unsupported_transport")`.
- **Slow drip:** the sync `_read_capped` also stops at a whole-request deadline.
- **Tests (new):** `tests/unit/ollama/test_ollama_show_source.py`,
  `tests/unit/ollama/test_ollama_show_sync_deadline.py`, `tests/unit/core/test_parameter_discovery_post.py`,
  helper `tests/unit/ollama/_show_client.py`; `tests/conftest.py` appended an autouse POST egress
  guard (default transport -> `unreachable`, so route tests on a machine running Ollama fall back to
  seeds instead of dialing it).
- **Approved prior-test edit:** `test_rows_publish_ollama_vision_as_image_only` now drives the async
  source — manifest `.claude/test-change-approvals/OME-1537.json`.
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN (append-only vs HEAD with the approved
  transition, ruff, format, pyright, no-enterprise, pytest + coverage).
- **Deviations:** (1) POST is a sibling core Protocol, not a new member of `DiscoveryHttpClient`:
  adding the member broke 132 pyright checks on prior-test GET-only doubles (append-only). (2)
  `register_models()` still makes the pre-existing cached `/api/tags` call (it is how seeds are
  found); "no network" is enforced for `/api/show`. (3) The sync `discover_ollama_input_modalities`
  has no listing caller now but is kept (bounded) because deleting it means deleting this PR's own
  tests, outside the approved change set — candidate cleanup with owner approval.

### Review round 3 (HupBaHa 2026-10-21T15:00Z, Medium)

- **Operator byte limit:** async `/api/show` probes now cap each body at
  `min(DiscoveryLimits.max_bytes, SHOW_MAX_BYTES)` — a stricter `AIGW_DISCOVERY_MAX_BYTES` wins, a
  looser one never raises the 1 MB show cap. Regression: `tests/unit/ollama/test_ollama_show_operator_limit.py`
  (new file; no prior test edited).
