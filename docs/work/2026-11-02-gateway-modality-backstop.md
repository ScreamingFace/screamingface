---
ticket: OME-1807
stack: aigateway
status: done
started: 2026-11-02
finished: 2026-11-04
---

# gateway-modality-backstop — refuse a media part the routed model's published modalities lack

## Intent

OME-1807: a PDF `file` part sent through OpenRouter to an image-only model
(`mistralai/mistral-small-3.2-24b-instruct`, published `input_modalities` `[text, image]`) is
billed (HTTP 200, 155 in / 11 out, 0.002013825 credits) and then reported as `provider_error`,
`permanent: false`. Evidence: branch `e2e-image-pdf`,
`docs/work/2026-11-02-e2e-image-pdf/evidence/refusal_pdf_to_image_only/`. The gateway now refuses
before dispatch with the typed 422 `unsupported_content_part` when the routed model's published
modalities lack the part's modality (`image_url` -> `image`, `file` -> `pdf`). Engine admission
(OME-1803, #1645) stays the primary, fail-closed refusal; this is the gateway backstop.

## Findings that forced a stop (before the decisions)

1. At request time the modalities live only on `ModelEntry.input_modalities` /
   `plugin.model_input_modalities(entry)`; for OpenRouter, HuggingFace and Ollama the evidence
   exists only on live-catalog entries. Seeds carry `None`.
2. `core/model_catalog.py` documented "consulted off the chat critical path only", and
   `entries_for` may refresh (dial) on a cold cache.
3. "Unknown = text-only" at the gateway would refuse images to vision models that work today
   (cold/disabled catalog, unlisted ids, family tables' unmatched families).

## Owner decisions (Sergey, 2026-11-02)

- **A — refuse only on published evidence.** Unknown passes as before. The port tells unknown
  from declared text-only; family tables keep their current behaviour and gain no new
  declarations. Engine admission stays strict.
- **(i) — chat reads a cached snapshot, never refreshes one.** The catalog rule becomes "chat
  may read a snapshot, never refresh one".

## Changes

- `core/plugin_base/_contract.py`: new port `model_input_modality_evidence(entry) -> tuple | None`
  (default: `entry.input_modalities`); `model_input_modalities` now derives from it (unknown ->
  text-only), so publication is unchanged.
- `core/input_modalities.py`: `declared_family_evidence` (None outside every family);
  `declared_family_modalities` delegates to it.
- Anthropic, OpenAI, Gemini, Codex, Antigravity plugins: override the evidence port with
  `declared_family_evidence` instead of overriding `model_input_modalities`. Tables untouched.
- `core/parameter_discovery_cache.py`: `ObservationCache.peek` — pure read, last-good value within
  ttl + stale window, same revision.
- `core/model_catalog.py`: `ModelCatalog.snapshot_entries` (never dials, never opens a slot);
  docstring invariant updated per decision (i).
- `core/model_capabilities.py`: `routed_model_modality_evidence` — snapshot entry, then admitted
  entry, else the bare id asked of the plugin. Never `register_models()` (Ollama seeds dial).
- `core/content_parts.py`: `check_input_modalities` — judges `image_url`/`file` by type only;
  `None` admits everything; reason `modality_unsupported <image|pdf>`.
- `routes/chat.py`: `_admit_media` calls it after the data:-only guard, before cache, credentials
  and dispatch.

## Tests (append-only)

- `tests/unit/test_chat_modality_backstop_route.py`: OpenRouter PDF to image-only model -> 422,
  no cache/credential/upstream call, no catalog dial (sync + stream); image to that model passes;
  PDF-capable model passes; declared text-only refuses an image and still takes text; unpublished
  row and unlisted id pass; cold catalog passes and chat never dials; discovery off passes; admitted
  entry with evidence is checked; text-only request unchanged; OpenAI `o3-mini` (declared
  text-only) refuses an image; families outside a table and full-capability families pass.
- `tests/unit/core/test_modality_backstop.py`: helper, family evidence, lookup, per-plugin port.
- `tests/unit/core/test_model_catalog.py` (appended): `snapshot_entries` read semantics.

## Acceptance

- OpenRouter PDF to an image-only model: 422 `unsupported_content_part`, no upstream call.
- PDF-capable model passes; text-only requests unchanged; adapter checks unchanged.

## Outcome

- **Actual files:** as listed under Changes, plus the three test files.
- **Commits:** see branch `OME-1807-gateway-modality-backstop`.
- **Gates:** `run_gates.py aigateway --base origin/main` — ALL GATES GREEN (append-only, ruff,
  format, pyright, no-enterprise, pytest 7647 passed / 107 skipped (pre-existing opt-in live)).
- **Deviations:** behaviour change for OpenAI `o3-mini`: an image is now refused at the gateway
  (its table declares text-only). The backstop only fires while a snapshot is cached (within
  ttl + stale window, 65 min for OpenRouter); a cold catalog passes by design.

## Owner ruling (2026-11-03, HupBaHa review on #1651)

Unknown modalities are admitted at the gateway: the gateway refuses only on published evidence. The `["text"]` that `/v1/models` publishes for an unknown model (OME-1537) is a listing default, not admission evidence. Engine admission (#1584, OME-1803/#1645, OME-1809) is the strict, fail-closed check and treats unlisted as text-only. The divergence for unknown models is intentional. It is recorded on Linear OME-1807, and the `acme/no-architecture` route test pins it.

- **Merged:** PR #1651, squash `89e6acfeb`, 2026-11-04 (approved by HupBaHa). Owner ruling 2026-11-03: refuse only on published evidence; an unknown model passes.
