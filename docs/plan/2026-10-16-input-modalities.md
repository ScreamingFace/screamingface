# Plan — input modalities on `/v1/models` (OME-1537)

Spec: `../spec/2026-10-16-input-modalities.md`. Stack: `aigateway` (sdlc-python).

1. Core vocabulary `core/input_modalities.py` + tests (normalize: filter, force text, order, dedupe).
2. `ModelEntry.input_modalities` (compare=False) + hook `model_input_modalities` default in
   `plugin_base/_contract.py`; `model_row` emits normalized `input_modalities`. Contract test.
3. OpenRouter: pure `parse_page_input_modalities`, `map_openrouter_modalities`; fetch walk
   collects the map (`fetch_live_model_catalog`), `live_listing_entries` attaches evidence.
4. HuggingFace: pure `parse_router_input_modalities`; listing discovery source +
   `discover_live_models` enriching configured entries.
5. Ollama: `discover_ollama_capabilities` (`/api/show`, cached, fail -> unknown);
   `register_models` attaches `vision` -> `image`.
6. Declared family tables: Anthropic, Antigravity, Gemini, Codex (hook only), OpenAI.
7. Gates, live e2e on port 9122 (no Codex chat), ledger outcome, PR.
