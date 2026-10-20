---
ticket: OME-1546
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-20
finished:
---

# image-token-accounting — account image and file input tokens (gateway half)

## Intent

Image and PDF input cost is invisible today: it is folded into `prompt_tokens` and no field says
how much of it was media. The spike (`OME-1598`, 2026-10-16) found that no live provider's raw
usage carries a per-modality breakdown; only the Gemini API documents one
(`usageMetadata.promptTokensDetails[{modality, tokenCount}]`). This unit adds one image/file
input-token field to the usage every non-streaming chat answer carries, fills it from
`promptTokensDetails` where present, and states it as unknown (`null`, never `0`) everywhere
else. Totals do not change. The engine half (forwarding into `ai.url4.cost.usage`) is a
follow-up for the engine owner.

## Planned changes

- `apps/aigateway/src/aigateway/core/usage_modalities.py` (new): Gemini modality parser + key.
- `plugins/gemini_provider/message_adapter.py`, `plugins/antigravity_provider/message_adapter.py`:
  `_usage_from_response` fills `prompt_tokens_details.image_and_file_tokens`.
- `plugins/codex_provider/chat_handler.py`: explicit `null`.
- `tests/unit/test_usage_modalities.py`, `tests/unit/gemini/…`, `tests/unit/antigravity/…`,
  route test: new tests only.
- `docs/spec/2026-10-20-image-token-accounting.md`, `docs/plan/2026-10-20-image-token-accounting.md`.

## Test plan

- Parser: recorded Gemini usageMetadata (TEXT+IMAGE+DOCUMENT) → IMAGE+DOCUMENT sum; text-only
  breakdown → 0 (known zero); absent / not a list / malformed entry / negative / bool / unknown
  modality only → per spec; never a partial sum.
- Codex: explicit null, totals unchanged.
- Gemini + Antigravity adapters: breakdown present → value; absent → null; totals unchanged.

## Acceptance

- Field present on every Gemini / Antigravity / Codex answer with usage; absent (unknown) on
  LiteLLM pass-through providers.
- Filled from `promptTokensDetails`; `null` elsewhere; totals unchanged vs 2026-10-16 on
  anthropic, antigravity, openrouter/google/gemini-2.5-flash, ollama/qwen2.5vl:3b (live, port 9132).
- `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
