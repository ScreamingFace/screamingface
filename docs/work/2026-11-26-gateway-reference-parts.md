---
ticket: OME-1970
stack: aigateway
status: done
started: 2026-11-26
finished: 2026-11-26
---

# gateway-reference-parts — the chat route accepts Case files by blob reference (OME-1970, PR 5 of 9)

## Intent

PR 4 gave the gateway an upload route and an in-memory file store scoped to (caller, run token,
SHA-256). PR 3 gave both caches a key that hashes a **blob reference** (`blob:sha256/<64 hex>`)
as the stored file, so a reference request keys exactly like today's inline request. This unit
joins them on `POST /v1/chat/completions`: a content part may now carry a reference instead of a
`data:` URI; the route checks the run's scope before the cache lookup (decision 3), keys the
request through PR 3's entry points (decision 2), and swaps each reference for the stored file's
`data:` URI inside the upstream slot, so a waiting request holds only its small JSON. A missing
file, a wrong token or no token is answered `blob_unknown` before the lookup and before any
upstream spend.

## Planned changes

- `apps/aigateway/src/aigateway/core/content_parts.py`: `BlobRefPart`, `parse_blob_reference`;
  the admission checks (`check_messages`, `text_only`) accept it; adapter-side `parse_content`
  refuses an unresolved reference; `provider_media_refusal` reads its `x_media_type`.
- `apps/aigateway/src/aigateway/core/media_intake.py`: a valid reference passes the data:-only guard.
- `apps/aigateway/src/aigateway/core/blob_refs.py` (new): `BlobUnknown` (503 `blob_unknown`),
  `references_in`, `key_form`, `RunFiles` (scope check, live lookup, the in-slot swap).
- `apps/aigateway/src/aigateway/routes/chat.py`: the reference stage before capture and the
  cache lookup; streaming refusal; `files=` to the cache plan and the frozen-copy capture;
  `blob_unknown` never captured.
- `apps/aigateway/src/aigateway/routes/chat_dispatch.py`: an optional in-slot body step in the
  dispatch lambda, before the retry loop.
- `apps/aigateway/src/aigateway/routes/frozen_copies.py`: replay keys a reference request the same way.
- `apps/aigateway/tests/fixtures/gateway_error_codes/codes.json`, Engine
  `world/gateway_codes.py`: `blob_unknown`.
- `.claude/test-change-approvals/OME-1970.json`: rewritten for this branch (codes.json).
- `docs/spec/2026-11-11-attachment-blob-refs.md`: 5.2 wire shape as built, 5.7, 5.8.

## Test plan

- RED first. `tests/unit/core/test_blob_refs.py`: wire part parsing and its refusals; admission
  checks accept a reference and still apply role/file/modality policy; adapters refuse an
  unresolved one; key form and swap shapes; scope check; a file dropped after the check.
- `tests/unit/test_chat_blob_ref_route.py`, through the real app and the PR 4 upload route:
  reference call shares the inline call's cache key and cached answer; another run's token and
  no token get `blob_unknown` even with a cached answer; a file dropped before the slot gets
  `blob_unknown` with zero upstream calls; streaming + reference → 422; the provider receives the
  inline body byte for byte; a captured reference call stores the reference form under the
  inline digest.

## Acceptance

- The tests above pass; the touched existing test files, the code-declaration test and the
  Engine parity test pass; ruff, ruff format and pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. The reference stage lives in `_admit_media` (it already runs
  before accounting, capture and the cache stage, and accounts its own refusals) and the cache
  call in a `_look_up_cache` helper, which keeps `chat_completions` under ruff's statement cap.
  `checked_run_files` in `blob_refs.py` is shared by the chat route and the replay route.
- **Wire shape:** the spec's 5.2 shape, now the contract: `{"type": "image_url", "image_url":
  {"url": "blob:sha256/<hex>", "detail"?}, "x_media_type", "x_size"}` and the `file` twin with
  `file_data` and `filename`. Closed shape; a malformed one is the 422 `unsupported_content_part`.
- **PR 3's open questions:** (a) key form = the inline part minus `x_media_type`/`x_size`, a
  `BlobReference` in the URL slot (`blob_refs.key_form`); pinned by the route test that a
  reference call hits the inline call's cache entry and vice versa. (b) the key and the
  provider request use the STORED type (read from leading bytes at upload); `x_media_type` and
  `x_size` must equal the stored file's, else 422 `blob_reference_mismatch`. The Engine's seal
  spells the type from the same signatures, so the key carries `data:image/png;base64,`.
  (c) `MediaStore.get` takes its lock; `RunFiles._sent` is written on the loop before any later
  digest thread starts. (d) confirmed: pinned rows store the reference form, under the inline
  digest (route test); `RunFiles.lookup` falls back to the file actually sent, so a file dropped
  during a long provider call still captures.
- **Codes:** `blob_unknown`, 503 (the Engine reads 429/5xx as not permanent), for another run's
  token, no token, never uploaded or dropped; before the cache lookup and inside the slot;
  never captured into a frozen copy and never routed through the dispatch-failure funnel (no
  credential marking). 422 `unsupported_content_part` reasons: `malformed_blob_reference`,
  `blob_reference_unexpected_field`, `blob_reference_x_media_type`, `blob_reference_x_size`,
  `blob_reference_filename`, `blob_reference_mismatch`, `blob_reference_streaming`,
  `unresolved_blob_reference`.
- **Commits:** `306fbbc1f` feat(aigateway): accept Case files by blob reference on the chat
  route; then docs(spec): this ledger and the spec's 5.2, 5.7 and 5.8.
- **Gates:** relevant tests only, per the owner rule (no `run_gates.py`): the 2 new files (50
  tests) plus 50 existing unit files that import or route through a changed module (content
  parts, media intake, chat route and dispatch, frozen-copy capture and replay, the cache
  stage, the code declaration, PR 3/4's files): 1322 passed. Engine
  `test_gateway_codes_parity.py` 2 passed. ruff check, ruff format, pyright clean on the 8
  touched aigateway files; ruff clean on the Engine file. Append-only check vs `upstream/main`
  green with the rewritten `.claude/test-change-approvals/OME-1970.json`.
- **Deviations:** (1) The replay route (`frozen_copies.py`) was wired too: a reference replay
  must hash the file to find its pinned entry, so it scope-checks like a live call. This
  amends the spec's "replay never resolves the reference". (2) `in_slot` is passed to the
  dispatch only for a reference call, so an inline call's dispatch call is unchanged (an
  existing test stubs the dispatch with the old signature). (3) About 600 source lines (half
  docstrings) and 700 test lines, over the ~400 LoC estimate. (4) The gateway code is
  `blob_unknown`, not the ticket's `x.blob_unknown`: the gateway's code list admits only
  `[a-z][a-z0-9_]*`; the Engine's `x.` name is PR 8's.
