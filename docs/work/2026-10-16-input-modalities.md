---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway
status: in_progress
started: 2026-10-16
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
