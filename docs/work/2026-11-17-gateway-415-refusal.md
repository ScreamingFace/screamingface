---
ticket: OME-1946
stack: python
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# gateway-415-refusal — a provider 415 on a media request is the `unsupported_content_part` refusal

## Intent

A provider that rejects a request's image/file part with HTTP 415 (seen: Hugging Face router →
DeepInfra, `moonshotai/Kimi-K3:deepinfra`, a GIF: `415 Unsupported media type`) surfaced from
`apps/aigateway` as a generic `provider_error`, so the url4 caller saw a non-admission failure.
The gateway already has the typed refusal for "this provider cannot carry this part" — 422
`unsupported_content_part` (`core/content_parts.py::UnsupportedContentPart`), which the Engine
connector translates to url4 `intent_error` (`world/attachment_parts.py::intent_error_for`).
A provider 415 on a request that carries image/file parts becomes that refusal; a 415 on a
text-only request keeps today's mapping. Not retried, not cached.

## Planned changes

- `apps/aigateway/src/aigateway/core/content_parts.py` — a provider-neutral
  `provider_media_refusal(status, messages, *, provider)` returning the `UnsupportedContentPart`
  for a 415 on a request with image/file parts (reason `provider_unsupported_media <mime,…>`),
  else `None`.
- `apps/aigateway/src/aigateway/routes/chat.py` — both dispatch-failure branches (plugin
  `HTTPException` and LiteLLM exception families) consult it before rendering.
- No Engine change.

## Test plan

- Unit (core): 415 + inline GIF image part → 422 detail with code, provider, `part_type`
  `image_url`, reason naming the MIME; 415 + PDF file part → `part_type` `file`; 415 + remote
  image → reason without MIME; 415 text-only → `None`; non-415 + image → `None`; malformed
  content never raises.
- Route (HF plugin, LiteLLM `APIError(status_code=415)`): media request → 422 body exactly the
  refusal shape, ONE upstream dispatch (no retry), no request-cache write; text-only request →
  415 `provider_error` unchanged.

## Acceptance

- The 422 body is `UnsupportedContentPart.info`, which `intent_error_for` translates.
- Gates green: ruff check, ruff format --check, pyright, pytest -n auto.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <counts>
- **Deviations:** <or "none">
