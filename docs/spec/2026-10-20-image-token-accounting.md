# Account image and file input tokens (gateway half)

Status: approved for implementation · Date: 2026-10-20 · Epic: `OME-1529` · Implements: `OME-1546`
(gateway half) · Builds on: `OME-1598` spike findings (2026-10-16)

## Problem

Image and PDF input is billed inside `prompt_tokens`, and nothing says how much of it was media.
The spike measured it only as a delta against a text-only call (Antigravity image +1098 / PDF
+527, Anthropic +68 / +1585, Codex +73 / +36). It also found that:

- no live provider's raw usage carries a per-modality breakdown (Antigravity / Gemini Code Assist,
  Anthropic, OpenRouter, Ollama, Codex Responses);
- the Gemini API documents one, `usageMetadata.promptTokensDetails: [{modality, tokenCount}]`,
  with modalities `TEXT | IMAGE | AUDIO | VIDEO | DOCUMENT`. The direct Gemini route cannot be
  exercised live from this setup, so it is proven from a recorded response in the documented shape.

## Decision

### Where the field lives

`usage.prompt_tokens_details.image_and_file_tokens` in the OpenAI-shaped `usage` object of a
non-streaming `POST /v1/chat/completions` answer whose usage the gateway itself converts
(Gemini, Antigravity, Codex). Absent elsewhere — see below.

| Value | Meaning |
|---|---|
| integer `>= 0` | the provider reported a per-modality breakdown; this is IMAGE + DOCUMENT |
| `null` or key absent | unknown — the provider reported no breakdown. **Never `0` for unknown.** |

It is a **non-additive subset** of `prompt_tokens` (like `cached_tokens`): it is already inside the
inclusive input total, so `prompt_tokens`, `completion_tokens`, `total_tokens` and every cost figure
are unchanged.

WHY the OpenAI `usage` object and not `_aigw.usage_accounting.attempts[].usage.input`:

1. `_aigw` attempts exist only for the two accounted providers (Anthropic, OpenRouter). Gemini,
   Antigravity, Codex and Ollama are `accounting_not_supported`, and for them the engine already
   falls back to `usage` (`world/connector.py::_report_usage`). One location reaches every
   provider; the `_aigw` one would reach exactly the two providers that never report a breakdown.
2. Prior tests pin `_aigw ... usage.input` by exact dict equality (five call sites). Tests are
   append-only, so a new key there is a prior-test change.

The key name is the gateway's own, not LiteLLM's `image_tokens`: LiteLLM's Gemini transformer folds
`DOCUMENT` into `text_tokens`, and this field must count files.

### Filling it — Gemini and Antigravity adapters

Both adapters build `usage` from `usageMetadata` with the same parser
(`core/usage_modalities.py::image_and_file_tokens_from_gemini`):

- `promptTokensDetails` absent, not a list, or empty → `null`.
- every entry must be an object with a string `modality`; `tokenCount` absent means `0` (proto3
  JSON omits zero values), present must be an integer `>= 0` (bool refused).
- any malformed entry → `null` for the whole field. A partial sum would be a false known value.
- the result is the sum of `IMAGE` and `DOCUMENT` entries (case-insensitive), `0` when the
  breakdown lists only other modalities. A sum over `2**53 - 1` → `null`.

Antigravity uses the same parser because Code Assist wraps the same `usageMetadata`; the spike saw
no breakdown there, so in practice it yields `null` until the upstream starts sending one.

### Stating "unknown" — per adapter, not in the route

- **Codex** (gateway-converted): the Responses usage carries only `input_tokens_details
  {cached_tokens, cache_write_tokens}` (observed live 2026-10-20), so the adapter writes
  `prompt_tokens_details: {"image_and_file_tokens": null}`.
- **Gemini / Antigravity** (gateway-converted): the parser above; `null` without a breakdown.
- **LiteLLM pass-through providers** (Anthropic, OpenRouter, Ollama, …): the key is **absent**,
  which also reads as unknown — never `0`.

WHY not one stamp in the chat route (tried first, reverted): the gateway returns a pass-through
provider's body intact apart from `_aigw`, and three prior tests pin exactly that
(`test_openrouter_benign_error`, `test_openrouter_error_policy::test_native_usage_cost_and_metadata_preserved`,
and the cross-repo hit-shape fixture `test_cache_hit_contract_fixture`). Tests are append-only,
so an explicit `null` for pass-through providers is an owner decision, recorded as an open
question on `OME-1546`: either relax the "body intact" contract for `usage`, or carry the field
under `_aigw` and regenerate the hit-shape fixture (plus the engine's run-events fixture).

### Out of scope

- Streaming answers (usage arrives in a final SSE chunk; streaming bypasses accounting already).
- Frozen-copy replay (`routes/frozen_copies.py`) replays the captured body, which already carries
  the field when it was captured after this change.
- **Engine half**: forwarding the field into `ai.url4.cost.usage` (`world/connector.py`,
  `url4.streaming.protocol.taxonomy.TokenUsage`) — engine-owned; recorded as a follow-up on
  `OME-1546` and in the PR.
- Codex dropping `input_tokens_details.cached_tokens` — filed separately as a bug.

## Acceptance

- Unit: parser table (present, text-only, absent, malformed); adapter tests per provider
  (breakdown present / absent) for Gemini, Antigravity, Codex.
- Live (port 9132): image + PDF on antigravity show `image_and_file_tokens: null`; anthropic,
  openrouter/google/gemini-2.5-flash, ollama/qwen2.5vl:3b show the key absent (unknown); every
  `prompt_tokens` as on 2026-10-16.
- Live acceptance "non-zero image tokens on a provider that reports them" is NOT reachable: no
  live provider reports a breakdown. It stays open on the ticket.
