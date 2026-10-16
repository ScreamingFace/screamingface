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
