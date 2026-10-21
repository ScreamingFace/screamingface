# Spec — expose each model's input modalities on `/v1/models` (OME-1537)

Parent epic: `OME-1529` (image inputs in url4). Landing: `aigateway`.

## Problem

Nothing in a `/v1/models` row says whether a model can take an image or a PDF, so the engine
cannot refuse a blind model before it spends money. HuggingFace discovery already parses
`input_modalities` and drops it; OpenRouter's catalogue carries it and our parser ignores it.

## Contract

Every `/v1/models` row gains `input_modalities: list[str]`.

- Vocabulary: `"text"`, `"image"`, `"pdf"` — nothing else is ever emitted.
- Order is canonical (`text`, `image`, `pdf`), no duplicates, `"text"` always present.
- **Unknown means `["text"]`. Unknown never means vision.** A provider that has no evidence,
  a discovery that failed, a seed fallback, a dynamically admitted model: all `["text"]`.

## Architecture (hexagonal)

- Core (`core/input_modalities.py`): the vocabulary, `TEXT_ONLY`, `normalize_input_modalities`
  (filters to vocabulary, forces `text`, canonical order). Core never names a provider.
- `ModelEntry` gains an optional `input_modalities` evidence field (`compare=False`, default
  `None`) so a provider's live listing can carry per-model evidence through the existing
  process-local snapshot without changing entry equality.
- Plugin hook `ProviderPluginBase.model_input_modalities(entry)`: default returns the entry's
  discovered evidence, else `("text",)`. Plugins with declared tables override it.
- `model_row` calls the hook and normalizes the result — a plugin cannot publish an
  out-of-vocabulary value or drop `text`.

## Sources

| Provider | Source | Mapping |
|---|---|---|
| OpenRouter | live catalogue `architecture.input_modalities` (verified 2026-10-16: list of `text`/`image`/`file`/`audio`/`video`) | `text`, `image`; `file` -> `pdf` (OpenRouter's PDF guide: PDFs travel as the `file` content type and go to the model natively when it "supports file input natively"); audio/video dropped |
| HuggingFace | router catalogue `architecture.input_modalities` (the parser already reads it) via a new listing-discovery source that enriches the configured entries | `text`, `image`; anything else dropped |
| Ollama | `POST /api/show` `capabilities` per installed model (verified live: `qwen2.5vl:3b` -> `[completion, vision]`, `qwen3:14b` -> `[completion, tools, thinking]`) | `vision` -> `image`; never `pdf` (no working PDF path: LiteLLM's Ollama path silently drops file parts today; the explicit refusal lands with OME-1641 / PR #1447) |
| Anthropic | declared family table | `claude-*` -> text, image, pdf |
| Antigravity | declared family table | `gemini-*` -> text, image, pdf; anything else text |
| Gemini (gemini-cli) | declared family table | `gemini-*` -> text, image, pdf |
| Codex | declared family table, hook only (`models.py`/`chat_handler.py` untouched — another unit owns them) | `gpt-5*`, `gpt-6*` -> text, image, pdf (verified live with `gpt-6-astra`) |
| OpenAI (direct) | declared family table | `gpt-5*`, `gpt-4.1*`, `gpt-4o*`, `o3*`, `o4*` -> text, image, pdf (OpenAI documents image + PDF file input for these families) |

Failure modes stay conservative: OpenRouter/HF listing failure -> seed fallback -> `["text"]`.
Ollama (review round 2, owner decision 2026-10-21): `/api/show` probes run only in the async
Ollama `model_discovery_source` through the `ModelCatalog` — `register_models()` returns
probe-free text-only seeds, so `AIGW_DISCOVERY_ENABLED=false` means zero probes. A probe round is
bounded (4 in flight, one 5 s deadline for the round, each body <= 1 MB with a total per-request
deadline) and all-or-nothing: any failed probe keeps the last-good snapshot, or the seeds when cold.

## Out of scope

The engine's per-type file policy (consumer, separate ticket); dispatch-side refusal; admitted
OpenRouter models (they report `["text"]` until a later unit threads evidence through admission).
