# Harden file intake in the gateway

Status: draft · Date: 2026-10-20 · Epic: `OME-1529` · Implements: `OME-1542` · Stack: aigateway

## Problem

1. **No body cap.** `routes/chat.py` reads the whole body (`request.json()`); nothing in the app,
   uvicorn or ingress bounds it.
2. **The gateway fetches caller URLs.** LiteLLM downloads caller-supplied references from inside
   our process (survey below). Nothing filters them on the LiteLLM-backed providers.
3. **Anthropic drops system images.** The OAuth path (`chat_handler._content_to_text_blocks`)
   keeps only text blocks of a system message and answers 200 without the image. The API-key path
   (LiteLLM `translate_system_message`) turns the part into `{"type":"image_url","text":null}`, an
   upstream 400.
4. **Cache cost.** Base64 bodies are hashed in full per lookup; a remote `image_url` is keyed by
   its URL, not its content.

## Where our process would dial a caller URL (litellm in `uv.lock`)

| Provider (plugin) | Part | What happens today |
|---|---|---|
| anthropic (LiteLLM) | `image_url` `http://` | `convert_url_to_base64` — **we fetch** |
| anthropic (LiteLLM) | `image_url` `https://` | sent as a `url` source — Anthropic fetches |
| ollama (LiteLLM `ollama_chat`) | `image_url` `http*` | `convert_to_ollama_image` — **we fetch** |
| openai / openrouter / huggingface / local (OpenAI wire) | `file.file_id` starting `https://`, `http://`, `www.` | `_handle_pdf_url` — **we fetch** |
| openai / openrouter / huggingface | `image_url` `http(s)` | passed on — the upstream fetches |
| gemini, antigravity | any remote | already refused (`check_messages`, OME-1541) |
| codex | `image_url` `https://`/`http://` | passed on as `input_image.image_url` |

Codex: `plugins/codex_provider/chat_handler.py::_input_part` copies the URL string into the
Responses payload and POSTs it to the ChatGPT backend; no code in the Codex plugin, the route or
LiteLLM (not on this path) issues a request to that URL. OpenAI fetches it, not us (OME-1541
decision) — Codex keeps it, and is the only provider that does.

## Design

### 1. Request body cap — `middleware/body_cap.py`

- Setting `max_request_bytes` (`AIGW_MAX_REQUEST_BYTES`), default **8 MiB = 8 388 608 bytes**,
  `gt=0`. Basis: MMMU's largest Case is 3.78 MB inline (Khoa, OME-1542, 2026-10-20); 8 leaves room
  for HLE / MathVista, which are not measured yet.
- Pure ASGI middleware, app-wide (every route reads its body through it), inside `CallIdMiddleware`
  so refusals carry the call id.
  - A declared `Content-Length` over the limit: 413 at once; the body is never read.
  - Otherwise `receive` is wrapped and counts the bytes actually delivered. The chunk that would
    take the total past the limit is **not** handed to the app; the read raises a 413 instead. So a
    missing, lying or chunked length cannot bypass the cap, and the app never holds more than the
    limit (the counter is the middleware's only state).
  - If anything downstream swallows that exception and starts another response, the middleware
    replaces it with the 413 (fail closed).
- 413 body: `{"detail": {"code": "request_too_large", "limit_bytes": N, "message": "Request body
  exceeds the gateway limit of N bytes (X MiB)."}}`.
- Per-path limit: `POST /v1/admin/cache/snapshots` already has its own, larger cap
  (`AIGW_CACHE_UPLOAD_MAX_BYTES`, compressed archive). That path is bounded by
  `cache_upload_max_bytes + 1 MiB` (multipart envelope), not exempted.

### 2. data: URIs only — `core/media_intake.py`

`refuse_remote_media(messages, provider=…, allow_remote_image_urls=…)`, called by the chat route
for every provider **before the cache stage** (so a refused request can neither hit nor fill the
cache) and before any credential or dispatch:

- `image_url` parts: the URL must be a `data:` URI. `http(s)://` → 422 `remote_url` (unless the
  provider opted in); anything else → 422 `not_data_uri`.
- `file` parts: `file_data` must be a `data:` URI (`http(s)`/`www.` → `remote_url`, else
  `not_data_uri`); any `file_id` → 422 (`remote_url` when URL-shaped, else `file_id`) — the gateway
  holds no Files upload, and LiteLLM fetches URL-shaped ids.
- Any other non-text part: a string under a URL-bearing key (`url`, `image_url`, `file_url`,
  `video_url`, `audio_url`, `uri`, `file_uri`, `file_id`, `file_data`), at any depth, that is
  `http(s)://` or `www.` → 422 `remote_url`. Text is never inspected, so a URL in prose passes.
- A part nested deeper than 32 levels → 422 `too_deep` (bounded walk, fail closed).
- Error: the existing `content_parts.UnsupportedContentPart` (typed 422, `code
  unsupported_content_part`). `content_parts.py` itself is not edited (PRs #1447 / #1441 touch it).
- Opt-in: `ProviderPluginBase.forwards_remote_image_urls = False`; Codex sets `True`. It relaxes
  only `http(s)` **image** URLs; files stay data:-only.

Why not `check_messages` on every LiteLLM provider: its parser fails closed on every part type it
does not model, which would newly refuse what those providers carry today (Anthropic `thinking`
blocks on replayed turns, OpenAI `input_audio`). The guard here refuses exactly the references
and nothing else; the per-plugin `check_messages` calls stay as they are.

### 3. Anthropic system media → 422

`AnthropicProviderPlugin.prepare_chat_body` runs `content_parts.text_only(..., role="system")` on
every `system` message and on a top-level `system` field — a non-text part raises the typed 422
(`reason: media in a system message`) on both the OAuth and the API-key path. The global-cache
projection returns `CacheBypass` for such a body, so an entry stored while the OAuth path still
dropped the image cannot answer it (prepare runs after the cache stage).

### 4. Cache keys — no change

Once (2) runs before the cache stage, no cacheable request carries a URL: every provider with a
global-cache projection refuses remote references, and Codex — the only provider that forwards
them — has no projection (always bypasses). A test pins that invariant. So "keyed by its URL, not
its content" cannot occur.

Hashing only the `data:` payload would not remove work: the payload must still be hashed. Measured
on an 8 MiB body (this machine): canonical JSON + SHA-256 ≈ 17 ms, SHA-256 of the payload alone
≈ 3 ms — at most ~14 ms saved per maximal request, against provider latencies of seconds, in
exchange for a new key derivation (a revision bump that orphans every stored entry and a second
canonical form to keep collision-free). Not done; revisit if profiling shows the key on the path.

## Out of scope

Provider-side size limits (unverified, PR #1450); the engine resolving references to data: URIs
(OME-1545); `check_messages(allow_files=…)` for Ollama (PR #1447).

## Verification

Unit tests per section; live e2e on :9131 — 9 MB → 413 naming the limit; 7 MB data image to
`anthropic/claude-haiku-4-5` accepted (or the provider's own limit reported); https image URL to
anthropic, `ollama/qwen2.5vl:3b`, `openrouter/google/gemini-2.5-flash` → 422 `remote_url` with zero
hits on a local logging HTTP server; Anthropic system image → 422; PNG/PDF runner on anthropic and
antigravity still pass.
