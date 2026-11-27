---
ticket: OME-1970
stack: aigateway
status: done
started: 2026-11-26
finished: 2026-11-26
---

# gateway-upload-store — the gateway's upload route and in-memory file store (OME-1970, PR 4 of 9)

## Intent

Case files (pictures, PDFs) ride every model call inline as base64 today, so a 5-member Fusion
sends an 18.35 MB PDF six times. OME-1970's design has the Engine upload each file ONCE per run to
the gateway and then send a **blob reference** (`blob:sha256/<64 hex>`) in each call. This unit
builds only the receiving side: a streamed upload route with its own 15,000,000-byte per-file cap
(decision 4), signature-checked types, the digest verified while reading, and `MediaStore`, an
in-memory, byte-bounded, least-recently-used store keyed by (caller, SHA-256 of the run's token,
file digest) so a digest alone never reaches a file (decision 3). It also amends the blob-reference
spec to the upload design (decision 10). The next PR (PR 5) reads the store when it parses
reference parts.

## Planned changes

- `apps/aigateway/src/aigateway/core/media_store.py` (new): `BlobScope`, `StoredMedia`,
  `MediaStore` (`put`, `get`), the signature table, `receive_upload` (the streamed, capped,
  hashing reader) and its typed refusals.
- `apps/aigateway/src/aigateway/routes/blobs.py` (new): `PUT /v1/blobs/sha256/{digest}`.
- `apps/aigateway/src/aigateway/middleware/body_cap.py`: an exempt-prefix list so the upload
  route takes its own cap instead of the app-wide 12 MiB.
- `apps/aigateway/src/aigateway/config.py`: `blob_store_max_bytes`, `blob_scope_ttl_seconds`.
- `apps/aigateway/src/aigateway/main.py`: build the store, mount the router, exempt the prefix.
- `apps/aigateway/tests/fixtures/gateway_error_codes/codes.json` + Engine mirror
  `apps/screamingface-engine/src/screamingface_engine/world/gateway_codes.py`: the new codes
  (the parity test pins them equal).
- `docs/spec/2026-11-11-attachment-blob-refs.md`: decision 10 amendment.

## Test plan

- Store: another run's token gets nothing; no token gets nothing; another caller with the same
  token gets nothing; LRU eviction under the byte budget; a re-put does not double-count; a scope
  expires after its TTL.
- Reader: an oversize stream is refused on the crossing chunk without pulling further chunks;
  a digest mismatch is refused; a non-allowed type is refused by leading bytes.
- Route: happy path stores the file's base64; oversize, mismatch, wrong type, missing or malformed
  token, malformed digest refused with typed codes; the route is exempt from the 12 MiB cap in the
  real app; no file is opened for writing during an upload; the token and file bytes never appear
  in a log record.

## Acceptance

- The tests above pass; ruff, ruff format and pyright are clean on the touched files; the gateway
  code-declaration test and the Engine parity test pass with the new codes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/blob_upload.py` split out of the store (the reader,
  the signature table and the typed refusals) and two new test files beyond the plan,
  `tests/unit/test_body_cap_exempt_prefix.py` and `tests/unit/test_blob_store_settings.py`.
  Route: `PUT /v1/blobs/sha256/{digest}`, token header `X-AIGW-Run-Token`. Settings:
  `AIGW_BLOB_STORE_MAX_BYTES` (40,000,000, provisional), `AIGW_BLOB_SCOPE_TTL_SECONDS` (58,800).
- **Commits:** `80bb218d4` — feat(aigateway): upload Case files once per run into a scoped
  in-memory store; then docs(spec): the spec amendment and this ledger.
- **Gates:** relevant tests only, per the owner rule (no `run_gates.py`): 122 passed across the
  5 new test files plus the body-cap, code-declaration, frozen-copy-settings and request-cap
  files; 75 passed in the route-inventory files (`test_main.py`, `test_app_regressions.py`,
  `test_auth_applicability_contract.py`, `test_frozen_copy_provenance.py`); Engine
  `test_gateway_codes_parity.py` 2 passed. ruff check, ruff format and pyright clean on every
  touched file. Mutation check: a file write and a token log line added to the route turned
  the disk and log tests red, then reverted.
- **Review fix (2026-11-27):** the store's budget counted only each file's base64, so tiny
  uploads (a 3-byte JPEG is charged 4 bytes) and fresh tokens held about 417 bytes of bookkeeping
  per file and an uncharged record per scope: about 600,000 tiny uploads would pass the 512 Mi
  pod limit. Each file is now charged `ENTRY_OVERHEAD_BYTES` (1024) and each live scope
  `SCOPE_OVERHEAD_BYTES` (1024); a scope is forgotten with its last file, keeping its deadline
  within one upload. The settings check counts both overheads. New store tests flood 10,000
  tiny files, with one token and with a fresh token each, and assert the file and scope counts
  stay bounded; 69 passed in the 5 PR test files, ruff and pyright clean.
- **Deviations:** (1) The gateway codes are `blob_digest_mismatch`, `blob_too_large` and
  `blob_unsupported_media_type`, not url4's `x.blob_digest_mismatch`: the gateway's code list
  admits only `[a-z][a-z0-9_]*` (`tests/unit/_gateway_error_code_scan.py`), so a dotted code
  cannot be declared. The spec's 5.8 says so. (2) `codes.json` is a modified file under
  `tests/`, so the append-only gate needs an owner approval in
  `.claude/test-change-approvals/OME-1970.json` (base blob `2255d4e8`, approved blob
  `ce13f5f9`); not written here, it is the owner's. (3) The upload route is exempt from the body
  cap middleware (a new `exempt_prefixes` argument) rather than given a per-path limit, so the
  caller sees the route's typed `blob_too_large` instead of `request_too_large`. (4) The diff is
  about 680 source lines (half docstrings and comments) and 825 test lines, over the ticket's
  ~400 LoC estimate. (5) The chart is not touched; both settings run on their defaults until
  PR 6 sets them from the Linux measurement.
