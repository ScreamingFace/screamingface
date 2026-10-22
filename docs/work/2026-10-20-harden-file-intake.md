---
ticket: OME-1542
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-22
---

# harden-file-intake — body cap, data: URIs only, Anthropic system images

## Intent

Image and file input (epic `OME-1529`) makes request bodies megabytes long and puts
caller-chosen references into `content` parts. Three holes follow: the gateway reads any body
into memory with no cap; LiteLLM fetches caller-supplied `http(s)` image/file URLs from inside
the gateway (Anthropic `http://`, Ollama any `http*`, OpenAI `file_id` URLs); and the
Anthropic OAuth path drops images in a system message and answers 200. This unit caps the
body (413 naming the limit), refuses every non-`data:` image/file reference with the typed
422 before the cache stage, and refuses system-message media on Anthropic. Spec:
`docs/spec/2026-10-20-harden-file-intake.md`, plan: `docs/plan/2026-10-20-harden-file-intake.md`.

## Planned changes

- `apps/aigateway/src/aigateway/config.py` — `max_request_bytes` (`AIGW_MAX_REQUEST_BYTES`, 8 MiB).
- `apps/aigateway/src/aigateway/middleware/body_cap.py` (new) + `middleware/__init__.py` + `main.py` wiring.
- `apps/aigateway/src/aigateway/core/media_intake.py` (new) — the data:-only guard.
- `apps/aigateway/src/aigateway/core/plugin_base/_provider.py` — `forwards_remote_image_urls = False`.
- `apps/aigateway/src/aigateway/plugins/codex_provider/plugin.py` — opt in (`True`).
- `apps/aigateway/src/aigateway/routes/chat.py` — call the guard before the cache stage.
- `apps/aigateway/src/aigateway/plugins/anthropic_provider/plugin.py` — system-media 422 + projection bypass.
- Tests under `apps/aigateway/tests/unit/` (new files only).

## Test plan

- Body cap: Content-Length over cap → 413 without reading; chunked/no Content-Length over cap → 413
  after at most cap bytes reach the app; lying Content-Length (small header, big body) → 413;
  exactly cap → passes; message names bytes and MB; snapshot upload path uses its own limit;
  setting validation (>0) and env override.
- Guard: `https://`/`http://` image URL → 422 `remote_url` for every provider but Codex; Codex
  keeps https; `file_id` (URL, `www.`, opaque) → 422; `file_data` URL → 422; non-data image string
  → 422; URL nested in an unknown part (e.g. `video_url`, Anthropic-native `source.url`) → 422;
  text containing a URL passes; data: image/file passes; text-only unchanged; refusal happens
  before the cache lookup and before dispatch (route test).
- Anthropic: system-message image / top-level `system` image → 422; text system unchanged;
  projection bypasses for system media.
- Invariant: no provider that forwards remote image URLs has a global cache projection.

## Acceptance

- Ticket acceptance: tests for the 413, the URL rejection on every LiteLLM-backed provider,
  and the system-image 4xx; text-only requests unchanged.
- Live e2e on :9131 per the dispatch (413 at 9 MB, 7 MB data image accepted, remote URL 422
  with zero hits on a local logging server, system image 422, PNG/PDF runner green).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `routes/chat.py` calls the guard through a small `_admit_media`
  helper wrapped around `strip_provider_dispatch_controls` (the route sat at ruff's PLR0915
  statement limit). Tests: `test_body_cap_middleware.py`, `test_body_cap_route.py`,
  `core/test_media_intake.py`, `test_chat_remote_media_route.py`,
  `anthropic/test_anthropic_system_media.py` (all new; no prior test touched).
- **Commits:** see the PR (squash-merged).
- **Gates:** `run_gates.py aigateway` — ALL GATES GREEN (append-only check, ruff, format, pyright,
  no-enterprise, pytest + coverage ≥ 80). New modules: body_cap 98 %, media_intake 97 % branch.
- **Live e2e (:9131, copied DB):** 9 MB body → 413 "8388608 bytes (8 MiB)" with Content-Length and
  chunked; 6.97 MB data:-image body (5.2 MB PNG) → anthropic/claude-haiku-4-5 200; remote
  http/https image URLs and a URL `file_id` → anthropic, ollama/qwen2.5vl:3b,
  openrouter/google/gemini-2.5-flash all 422 `remote_url`, **0 hits** on the local logging server;
  Anthropic system image → 422; runner PNG "4827" / PDF "ZEBRA-4127" on anthropic and antigravity
  6/6 correct; ollama image correct (its PDF is still dropped — PR #1447's fix, out of scope).
- **Deviations:** `check_messages` is not reused for the LiteLLM providers — its fail-closed parse
  would newly refuse `thinking` / `input_audio` parts; a dedicated guard (`core/media_intake.py`)
  runs at ingress for every provider instead, leaving `content_parts.py` untouched (no conflict with
  #1447 / #1441). Cache keys unchanged (spec §4: no cacheable request can carry a URL; pre-hashing
  saves ≤ ~14 ms per 8 MiB body).
- **2026-10-20 owner decisions (PR #1479):** Codex forwards **https** image URLs only — plaintext
  `http`, local or not, now gets 422 `remote_url_not_https` (new tests in
  `test_codex_https_only_route.py`, append-only). Strict 422s for opaque `file_id`s, raw base64
  image strings and URL keys in unknown parts are kept (behaviour change, release-noted).

## Review round 2 — HupBaHa changes requested 2026-10-22

Five findings on head `8589912db`; append-only tests, no prior test edited.

1. **HIGH** — middleware-authored 413s must close the connection: `BodyCapMiddleware._refuse`
   sends `Connection: close` (uvicorn httptools/h11 then close the transport; attacker input is
   never drained). Tests: real uvicorn on an ephemeral port + raw socket, declared-length and
   chunked overflow, socket EOF promptly after the 413 (keep-alive timeout set high).
2. **MEDIUM** — per-path limit looked up on the ROUTE path (`root_path` stripped as Starlette
   does). Test: `root_path=/prefix`, `path=/prefix/v1/admin/cache/snapshots` gets the special cap.
3. **MEDIUM** — Anthropic top-level `system` media refused at the route boundary: a core hook
   `ProviderPluginCore.refuse_inadmissible_media(body)` (default no-op) called inside
   `_admit_media`; the Anthropic plugin implements it. Route tests: unconnected / OAuth / API-key
   credential outcomes all 422 with zero cache and credential calls.
4. **MEDIUM** — one shared `content_parts.parse_data_uri` (the existing engine-conformant
   `_DATA_URI_RE`, a bounded header, strict base64 via `binascii`) used by `content_parts` and
   `media_intake`. Route tests for `data:`, `data:not-a-media-uri`, `data:image/png;base64,%%%`
   (image and file) → 422 before cache/credentials; pathological inputs < 100 ms.
5. **MEDIUM** — remote image scheme matched case-insensitively and normalized to lowercase in
   `content_parts`; the intake guard uses the same helper. Route-level mixed-case HTTPS regressions
   for Codex.

### Review round 2 — outcome

- **Commits:** `795cf8b87` (413 `Connection: close` + route-path limit), `e14f3a553` (shared
  `parse_data_uri` + case-insensitive remote scheme), `bc85f0751` (`refuse_inadmissible_media` hook).
- **Files:** `middleware/body_cap.py`, `core/content_parts.py`, `core/media_intake.py`,
  `core/plugin_base/_provider.py`, `plugins/anthropic_provider/plugin.py`, `routes/chat.py`. New
  tests only: `test_body_cap_connection_close.py` (real uvicorn, httptools + h11),
  `core/test_data_uri_envelope.py`, `test_chat_media_admission_route.py`. No prior test touched.
- **Gates:** `run_gates.py aigateway` — ALL GATES GREEN (6688 passed, 109 skipped; total 94 %;
  body_cap / media_intake / content_parts 100 %).
- **Deviations:** `_DATA_URI_RE` is unchanged (engine conformance tests pin it on both sides);
  `parse_data_uri` adds a 1 KiB header bound and strict base64 on top, so the gateway is now
  stricter than the engine's envelope check (the engine sends real `b64encode` output — no
  practical gap). Pathological 8 MiB inputs parse in ~10 ms (unbounded regex was ~200 ms).
  `prepare_chat_body` keeps its own system-media refusal as defense in depth.
