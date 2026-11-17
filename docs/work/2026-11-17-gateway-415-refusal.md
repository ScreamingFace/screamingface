---
ticket: OME-1946
stack: python
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
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

- **Actual files:** as planned — `apps/aigateway/src/aigateway/core/content_parts.py`
  (`provider_media_refusal`), `apps/aigateway/src/aigateway/routes/chat.py` (`_media_refusal_or`
  in both dispatch-failure branches); tests `tests/unit/core/test_provider_media_refusal.py`
  (15) and `tests/unit/huggingface/test_huggingface_media_415_route.py` (3).
- **Commits:** a6ef3b020 — fix(aigateway): report a provider 415 on a file part as
  unsupported_content_part
- **Gates:** ruff check pass; ruff format --check pass (916 files); pyright 0 errors;
  pytest 7920 passed, 119 skipped (serial — `pytest-xdist` is not installed in this app, so
  `-n auto` is rejected); `check_no_enterprise.py` OK. RED confirmed: 2 route tests fail
  without the fix (415 `provider_error`), the text-only control passes both ways.
- **Deviations:** reason vocabulary chosen here: `provider_unsupported_media[ <mime,…>]` —
  MIMEs are the request's own (distinct, request order); upstream text is never included.
  `part_type` is the first media part's (the upstream does not say which part it refused).
  Streaming is out of scope: a mid-stream failure still yields the SSE `provider_error` frame.
  A plugin whose prepared body is no longer OpenAI-shaped falls back to today's mapping.
