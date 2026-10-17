# Send images and PDFs to Gemini, Antigravity and Codex natively

Status: draft · Date: 2026-10-15 · Epic: `OME-1529` · Implements: `OME-1541` · Answers: `OME-1598`

## Problem

Three adapters flatten OpenAI `content` to one string and drop every non-text part:
`plugins/gemini_provider/message_adapter.py::_message_content_text`,
`plugins/antigravity_provider/message_adapter.py` (same code), and
`plugins/codex_provider/chat_handler.py::_message_content_text`. The caller gets a 200 answer from a
model that never saw the image. In a benchmark that scores as a wrong answer, not a skip.

The spike `OME-1598` could not be run in-process against staging (cluster auth and the
mesh-identity guard). Decision 2026-10-15: build the conversion, deploy it, and answer the spike
from outside over HTTPS. That is safe because the change cannot be worse than today: a part is
either accepted by the provider, or rejected with a 4xx the caller sees, never silently dropped.

## Design

### Core translator — `core/content_parts.py` (new)

Parses one message's OpenAI `content` into an ordered list of neutral parts:

| OpenAI part | Neutral part |
|---|---|
| `str` / `{"type":"text","text"}` | `TextPart(text)` |
| `{"type":"image_url","image_url":{"url":"data:<mime>;base64,<b64>"}}` (or a bare string url) | `ImagePart(mime, data_b64)` |
| `{"type":"image_url", … "https://…"}` | `ImagePart(url=…)` (remote) |
| `{"type":"file","file":{"file_data":"data:<mime>;base64,<b64>","filename"?}}` | `FilePart(mime, data_b64, filename)` |
| anything else (`input_audio`, unknown types, malformed data URI) | `UnsupportedContentPart` error |

Core never imports plugins; plugins import this module. Base64 payloads are passed through
unchanged (no decode/re-encode), only validated as a `data:` URI with a `;base64` marker.

### Error — `UnsupportedContentPart`

An `HTTPException` subclass, status **422**, detail
`{"error": "unsupported_content_part", "provider": "...", "part_type": "...", "reason": "..."}`.
Raised before any upstream call, so it never retries and never marks the credential as errored.

### Gemini and Antigravity

- Text runs keep today's shape: consecutive text parts are joined with `"\n"` into ONE `{"text"}`
  part. A text-only message is therefore byte-identical to today.
- `ImagePart` / `FilePart` (inline) → `{"inlineData": {"mimeType", "data"}}`, in content order.
- An image-only user turn is kept (today it is removed because its text is empty).
- Remote `ImagePart(url)` → 422 (`reason: remote_url`). The gateway does not fetch URLs (SSRF);
  the engine resolves references to `data:` URIs (`OME-1545`).
- System and tool messages with non-text parts → 422 (`systemInstruction` / `functionResponse`
  stay text).

### Codex (Responses API)

- Text-only messages keep `{"role", "content": "<string>"}` — byte-identical.
- A user message with media becomes `content: [ ... ]` with `{"type":"input_text","text"}`,
  `{"type":"input_image","image_url": "<data uri | https url>"}` and
  `{"type":"input_file","filename","file_data":"<data uri>"}`, in content order.
- Media on a non-user message (assistant, tool, system) → 422.

## Out of scope

Size caps and the SSRF policy for other providers (separate tickets); `/v1/models` input
modalities; image-token accounting (`OME-1546`); engine and url4 changes.

## Verification

1. Unit tests per translator and adapter (below, in the plan).
2. After deploy to staging: 12 calls over the public URL with a Cloudflare Access session —
   {gemini-cli, antigravity, codex, anthropic, openai} × {PNG "4827", PDF "ZEBRA-4127"} — recording
   status, answer, correctness and the gateway usage block. The table goes into `OME-1598`.
