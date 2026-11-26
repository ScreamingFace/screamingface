---
ticket: OME-1970
stack: aigateway
status: done
started: 2026-11-26
finished: 2026-11-26
---

# gateway-reference-cache-key — a request that carries a file by reference keys exactly like today's inline request

## Intent

PR 3 of 9 for OME-1970 ("today's cache key for a reference request"). Later PRs let the Engine
upload a Case file to the gateway once and then send a **blob reference** (`blob:sha256/<64 hex>`,
the SHA-256 of the file's bytes) where the file's base64 used to be. Both of the gateway's stores
key a request by the SHA-256 of its canonical JSON with the file's base64 inside: the response
cache (`core/request_cache/global_keys.py`) and the pinned cache a published run is replayed from
(`core/frozen_copy/store.py`). Owner decision 2 (26 Nov): the key stays exactly today's, so no
cached answer or pinned copy is lost and `KEY_REVISION` does not move. This unit adds a streaming
twin of `canonical_digest` that hashes the same bytes as today's canonical JSON with each
reference replaced by the stored file's `data:` URI, without building the whole string, and wires
both stores to it behind an optional file lookup (no caller passes one yet; PR 5, the gateway's
reference parts, will). The hash runs off the event loop.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/canonical.py` — `BlobReference`,
  `ReferencedFile`, `ReferencedFileLookup`, `UnknownBlobReference`,
  `canonical_digest_with_references(mapping, files)`; the json-safety guard learns to let a
  `BlobReference` through only for the twin.
- `apps/aigateway/src/aigateway/core/request_cache/global_keys.py` — optional `files` on
  `build_global_cache_key` / `build_attempt_cache_key`.
- `apps/aigateway/src/aigateway/core/request_cache/global_plan.py` — optional `files` passed through.
- `apps/aigateway/src/aigateway/routes/chat_cache_stage.py` — optional `files` on
  `look_up_global_cache`; with one, the plan runs in a worker thread.
- `apps/aigateway/src/aigateway/core/frozen_copy/store.py` — optional `files` on `request_digest`,
  `capture`, `find`; digest off the event loop; a stored request holds the reference text.
- New test `apps/aigateway/tests/unit/test_reference_cache_key.py`.

## Test plan

- RED first: the recorded inline request (`tests/fixtures/url4_attachment_cap_request/recipe.json`,
  "as the Engine really sends it") and the same request with a reference give equal keys in BOTH
  stores (response cache key + pinned-cache digest, and an end-to-end capture-by-reference then
  find-inline on the store).
- One changed byte of the file changes both keys.
- A reference the lookup does not hold raises `UnknownBlobReference`, named, in both stores (not a
  silent bypass).
- Property-style: over many shapes (nested parts, unicode text incl. U+2028, quotes, backslashes,
  control chars, several references, the same reference twice, empty containers, numbers, tuples,
  seeded random trees) the twin equals `canonical_digest` of the inlined mapping; guard parity
  (non-string key, NaN, unsupported type, too deep, non-dict Mapping).
- The hash runs on a worker thread, not the event loop's (lookup records its thread).

## Acceptance

- Reference request key == inline request key in both stores, proven from a recorded inline request.
- No `KEY_REVISION` change; every existing key test in the touched files stays green and unmodified.
- ~18 MB file hashes in well under 100 ms, off the event loop.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - NEW `apps/aigateway/src/aigateway/core/request_cache/reference_digest.py` — `BlobReference`,
    `ReferencedFile`, `ReferencedFileLookup`, `UnknownBlobReference`,
    `canonical_digest_with_references(mapping, files) -> str`. Writes the request with
    `canonical_material` (the one writer) with each reference as a random-nonce placeholder,
    then streams the hash, swapping each placeholder for `"data:<type>;base64,<b64>"` in 1 MiB
    slices. `canonical.py` is unchanged.
  - `global_keys.py` — new `build_reference_cache_key(..., files, attempt=None)`; `_key_result`
    takes an optional lookup.
  - `global_plan.py` — gates moved into a private `_plan` and key choice into `_key`;
    `build_global_cache_plan` is unchanged on the outside; new `build_reference_cache_plan(..., files)`.
  - `routes/chat_cache_stage.py` — `look_up_global_cache(..., files=None)`; with a lookup, the
    plan runs in `asyncio.to_thread`.
  - `core/frozen_copy/store.py` — `request_digest(..., files=None)`; `capture`/`find` take
    `files`, digest via `asyncio.to_thread`; a reference request's row stores `blob:sha256/<hex>`.
  - NEW `apps/aigateway/tests/unit/test_reference_cache_key.py` (226 tests).
- **Commits:** `feat(aigateway): key a blob-reference request exactly like today's inline request`
  (on branch `OME-1970-pr3-gateway-reference-cache-key`).
- **Gates:** per the owner's relevant-tests rule, no full suite: the 42 unit test files that
  import a changed module, 1038 passed; the four chat route files that monkeypatch the cache stage
  plus the projection purity sweep, 226 passed; ruff check + format and pyright clean on the 6
  touched files; `check_no_enterprise.py` OK. Measured: 18,346,668 bytes of base64 hash in 37.3 ms
  median by reference vs 38.3 ms inline, peak extra memory 3.0 MiB vs 39.4 MiB.
- **Deviations:**
  - Planned the twin inside `canonical.py` and a `files` parameter on `build_global_cache_key`
    and `build_global_cache_plan`. Three prior tests pin exactly those surfaces on purpose
    (`test_canonical_digest.py::test_every_exported_entry_point_applies_the_json_safety_guard`,
    `test_global_cache_key.py::test_the_builder_accepts_no_identity_profile_or_credential_input`,
    `test_global_cache_plan.py::test_the_planner_accepts_no_identity_profile_or_credential_input`).
    Changing a prior test needs the owner, so instead: the twin lives in a new module and reuses
    `canonical_material` itself (no second writer of the form), and reference requests get
    sibling entry points with their own signature tripwire test. No prior test was edited.
  - A pinned-cache row for a reference request stores the reference text, not the file (the
    stored request is never read back). The entry-size cap therefore measures that small form.
    PR 5 may revisit this.
