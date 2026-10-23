---
ticket: OME-1546
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-20
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

- **Actual files:** `core/usage_modalities.py` (new, parser + key); Gemini, Antigravity and Codex
  adapters; tests `tests/unit/test_usage_modalities.py`,
  `tests/unit/test_gemini_family_image_file_usage.py`, `tests/unit/codex/test_codex_image_file_usage.py`;
  spec, plan, ledger, `docs/tasks/2026-10-20-OME-1546-image-token-accounting.md`.
- **Commits:** `a1cf59d3b` feat(aigateway): report image and file input tokens in chat usage.
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN (append-only check, ruff, format, pyright,
  no-enterprise, pytest 6090 passed / 105 skipped, coverage 93%).
- **Live e2e (port 9132, 2026-10-20):** antigravity/gemini-3-flash text/image/PDF `prompt_tokens`
  8 / 1106 / 535 = 2026-10-16, field `null`. openrouter/google/gemini-2.5-flash 7 / 1045 / 1304
  = 2026-10-16, key absent (raw details carry only audio/video/cache). ollama/qwen2.5vl:3b
  26 / 94 / 33 = 2026-10-16, key absent. anthropic: NOT RUN — the Claude refresh token in both
  local DB copies is rejected (HTTP 400, re-auth required); its path is pass-through and unchanged.
- **Deviations:** (1) Planned central chat-route stamp (explicit `null` for every provider)
  reverted: it broke three prior tests that pin the pass-through body and the hit-shape contract
  fixture. Pass-through providers leave the key absent; explicit `null` there is an owner question
  on OME-1546. (2) `_aigw` taxonomy left unchanged (prior exact-dict tests). (3) Codex gets an
  explicit `null`. (4) Live non-zero acceptance unreachable: no live provider reports a breakdown.
  (5) Codex cached-tokens drop verified live and filed as OME-1683 (bug, Triage), not fixed.

## Review fix — PR #1481, HupBaHa 2026-10-22 (Medium: detail could exceed/outlive `prompt_tokens`)

- **Change:** `core/usage_modalities.py` adds `prompt_token_total_from_gemini` (shared validator:
  `promptTokenCount` must be a bounded non-negative int; absent/null/bool/float/string/negative/
  overflow → unknown) and `bounded_image_and_file_tokens_from_gemini` (publishes media only when
  the total is valid and `0 <= media <= prompt`, else `None`). Gemini + Antigravity
  `_usage_from_response` publish the bounded value. `_bounded_count` is shared with the breakdown
  parser (DRY; behaviour unchanged).
- **Choice:** `prompt_tokens` itself keeps its lenient `int(x or 0)` parsing — tightening it would
  change caller-visible totals (e.g. absent → 0 today). Only the new detail is gated.
- **Tests (new, append-only):** `tests/unit/test_image_file_tokens_bounded_by_prompt.py` — parser,
  bounded detail, and both adapters × absent/null/bool/float/string/negative/overflow/smaller.
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN (append-only, ruff, format, pyright,
  no-enterprise, pytest 6308 passed / 109 skipped, coverage 94%).
