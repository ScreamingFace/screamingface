---
ticket: OME-1545
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-28
finished:
---

# engine-attachment-parts — build image and file content parts in the engine connector

## Intent

The url4 run now carries a frozen, ordered `attachments[]` side-channel (`OME-1543`) and hands it to
every in-process model call as `Request.attachments`, but the engine connector's
`_messages(request.context, request.intent)` never reads it, so a picture or PDF named in a url4
expression never reaches the model (E2E evidence, 2026-10-28). This unit makes every model-calling
node (members, synthesizers, reducers) put those attachments on its last user message as OpenAI
content parts, per spec `docs/spec/2026-10-16-OME-1535-file-input-execution.md` F2 (layout), F3
(canonical encoding, integrity, engine key unchanged) and §2.7 gate 2 / D6 (judge refused by name).
Built on the `OME-1543` chain; the PR opens after #1478/#1482/`OME-1543` land.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/attachment_parts.py` (new): the
  `BlobReader` port, canonical `data:` URI encoding, sha256 verification, part building, and the
  last-user-message merge (D3).
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: build the parts per
  call and place them on the last user message; refuse them on a grading call.
- `apps/screamingface-engine/tests/unit/test_attachment_parts.py` (new).

## Test plan

- Image attachment → `image_url` part with a canonical `data:` URI, before the text.
- PDF attachment → `file` part (`file_data`, `filename` carried).
- Two attachments keep `attachments[]` order; `detail` carried to `image_url`.
- Text-only request: the gateway body is byte-identical to today (fixed expected bytes).
- Canonical encoding: padded standard base64, no line breaks, lowercased media type, no params.
- Integrity: bytes that do not hash to the digest → `x.blob_digest_mismatch`; snapshot without
  bytes uses the injected reader; no reader / reader miss → `source_not_found`.
- Grading call carrying attachments → `invalid_candidate_input` (D6).
- v1/v2 candidate envelope: parts land on the last user message only; v2 parts keep position.
- A synthesizer / reducer call through the world endpoint carries the same parts.

## Acceptance

- Every non-grading model call with attachments sends `[attachment parts…, text]` on its last user
  message; text-only calls are byte-identical to today; engine request key unchanged (F3).
- `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `world/attachment_parts.py` (new, 200 lines),
  `world/connector.py` (+26/-1: `_attachment_parts` + the placement in `_ModelEndpoint.__call__`),
  `tests/unit/test_attachment_parts.py` (new, 22 tests). No prior test touched.
- **Commits:** see branch `engine-attachment-parts` (feat(engine): build image and file content
  parts from the run's url4 attachments).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` — ALL
  GATES GREEN (append-only, ruff, format, pyright, layering, pytest + cov ≥80%, total 95.76%);
  `attachment_parts.py` 100% line coverage. url4 untouched, so its gates were not run.
- **Deviations:**
  - The reader is a run-scoped ContextVar binding (`bound_blob_reader`), not a
    `build_aigateway_world` parameter: two prior tests on origin/main pin the handler's slot
    allowlist (`test_request_scope_hardening`) and the url4-importer allowlist
    (`test_only_engine_extensions_import_url4`). The ContextVar also matches F3 step 1 (tenant +
    run from the run context). The new module therefore imports no url4: it reads attachments
    structurally (`AttachmentRef`) and raises `AttachmentPartError`, which the connector maps to
    `ResolutionError` (`source_not_found` / `x.blob_digest_mismatch`, permanent).
  - No production caller binds a reader yet (`OME-1540` store not built); today every url4
    attachment carries verified bytes in the frozen snapshot, so the reader path is a port only.
  - `connector.py` grows from 1634 to 1659 lines (already above the 450-line guideline); the logic
    lives in the new module to keep the growth to wiring.
  - Initial draft of the module preceded its tests (the connector tests were RED first).

### Round 2 (2026-10-28) — gateway `unsupported_content_part` → url4 `intent_error`

- **Decision:** owner (Sergey, 2026-10-28) — implement spec #1450 §4: the engine connector
  translates the gateway's `unsupported_content_part` refusal into url4 `intent_error`, keeping the
  response's permanence and carrying the gateway `info` as the cause. Only that code; every other
  gateway mapping unchanged. The sync run route stays 502 (url4-cloud contract, `test_rest.py`);
  a mount call answers 422 (`intent_error` in url4's table).
- **Files:** `world/attachment_parts.py` (+30: `GatewayContentPartRefusal`, `intent_error_for`,
  `INTENT_ERROR` / `UNSUPPORTED_CONTENT_PART`); `world/connector.py::_raise_for_status` (+7 wiring,
  1659 → 1666 lines). The cause is the Python `__cause__` (a `GatewayContentPartRefusal` holding a
  copy of the gateway `info`); on the wire `ErrorInfo` has only `code`/`message`/`permanent`, so
  the gateway's own `message` is the `intent_error` message the caller reads.
- **Tests (new only):** `tests/unit/test_unsupported_content_part_refusal.py` (9: translation,
  cause, permanence kept on a 503, four other codes unchanged, helper edges);
  `tests/unit/test_mount_routes.py` +2 appended (real chain `_raise_for_status` → `_error_info` →
  mount: 422 `intent_error` with the gateway message; `provider_refused` stays 502 unchanged).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN;
  `packages/url4/scripts/check_module_size.py` — all capped modules within baseline (url4
  untouched; connector.py is not on that list).

### Round 3 (2026-11-02) — merge #1587 F3, e2e F2 (`fetch_bytes` through the fair-share layer)

- **Merge:** `41629d9da` merges `origin/OME-1543-file-refs-carry` (F3 fix `815a6b9ad`). Its one
  conflict is `connector.py::_raise_for_status`, resolved per the owner decision of 2026-11-02:
  the intent branch raises `_GatewayRefusal(code=INTENT_ERROR, status=…, detail=text) from refusal`,
  and every other answer raises `_GatewayRefusal(code=code, …)`. The OME-941 filter moved to
  `_upstream_code()` (complexity limit). Test +1 appended to `test_unsupported_content_part_refusal.py`.
- **F2:** `438058add` — `runner/fair_share.py` binds `fetch_bytes` only when the inner layer has
  it (getattr, as url4's `BoundedIOLayer` does), admitted through the same gate. Tests: new
  `tests/unit/test_fair_share_fetch_bytes.py` (4: forwarded and gated at capacity 1, permit
  released on failure, absent without an inner port, and a gate-bound `build_executor` run whose
  https PNG reaches the fake gateway as an `image_url` part).
- **Gates:** `run_gates.py screamingface-engine --base origin/OME-1543-file-refs-carry` ALL GREEN
  (both commits).

## Amendment 2026-11-03 — shared live byte budget reaches local mode (push security review)

**Finding ("resource-cap-defeat").** A run's concurrent attachment flights could download and hold
about 20 × 20 MiB before the 8,000,000-byte per-run cap refused it. Fixed below this PR: #1482 adds
`FetchRequest.max_bytes` / `on_chunk` to the bytes path; #1587 makes the cap one live budget the
flights draw from as bytes arrive. Both merged here normally.

**This PR.** No source change: `FairShareIOLayer.fetch_bytes` already forwards the request object
unchanged, so the hook reaches the reading transport. New append-only test
`apps/screamingface-engine/tests/unit/test_fair_share_byte_budget.py` (2): the request passes
through by identity; 20 × 1 MiB attachments through `FairShareIOLayer(HttpIOLayer)` are refused
`attachments_too_large` with bytes read ≤ 8,000,000 + 20 × 65,536 and no model call.

**Gates.** `run_gates.py screamingface-engine --base origin/OME-1543-file-refs-carry` and
`run_gates.py url4 --base origin/OME-1543-file-refs-carry` ALL GATES GREEN; `check_module_size.py`
within baseline (`dag/_context.py` 455/455); `check_suppressions.py` 3/3; private-import ratchet green.

### Round 4 (2026-11-13) — PR #1588 review (HupBaHa @ `1ae16fb18`): fan-out memory, cap alignment

- **Merge:** `c0201b1d5` merges `origin/OME-1543-file-refs-carry` @ `a40347a18` (clean).
- **Blocker 1 (fixed) — one encoded copy per frozen snapshot, streamed request bodies.**
  `world/attachment_parts.py::_shared_uri`: a snapshot entry is verified and base64-encoded ONCE;
  every call of the run shares that one `data:` URI `str`, keyed by the entry's identity (never by
  equality — an equal entry of another run must not reuse this run's read) and dropped by
  `weakref.finalize` with the entry. A ref (empty body) is still read through the run-scoped reader
  and verified on every call (F3 authorization); only its encoding is shared.
  New `world/streamed_json.py`: a body holding a string ≥ 256 KiB is sent as a re-iterable stream
  of ≤ 64 KiB chunks with an exact `Content-Length`, byte-identical to httpx's `json=` encoding;
  every other body keeps `json=` (text-only parity). `connector.py::_post_attempt` picks the path.
  Probe (the reviewer's: 8,000,000-byte picture, URI 10,666,690 B, 8 concurrent calls held at a
  barrier): before, 170.8 MB traced while in flight; after, within `E + 8 × 256 KiB` in flight and
  `2E + 8 × 256 KiB` peak (the one transient `E` is the base64 bytes and their `str` while the shared
  URI is built). Tests (new): `tests/unit/test_attachment_fan_out_memory.py` (10).
- **Blocker 2 (STOPPED — needs owner call).** Arithmetic: gateway cap `C` = 8 × 1024 × 1024 =
  8,388,608 B. Decoded cap `D` = 6,000,000 → base64 4·⌈D/3⌉ = 8,000,000 B; with 20 parts the padding
  bound is ⌊4D/3 + 8·20/3⌋ = 8,000,053 B, leaving 388,555 B for `data:` prefixes, part JSON and the
  text envelope. (The largest `D` with 4D/3 ≤ C at zero envelope is 6,291,456.) Lowering
  `url4.dag._caps.MAX_ATTACHMENT_BYTES` to 6,000,000 fails 10 prior #1587 tests that pin the
  8,000,000 boundary literally, so per the loop's rule it was not changed here.
- **Merge 2:** `a23919733` merges `origin/main` (#1587 squash `2cd0cbf8d`; PR retargeted to main), clean.
- **Gates (after both merges):** `run_gates.py screamingface-engine` ALL GREEN (8,928 passed,
  354 skipped); `run_gates.py url4` ALL GREEN (3,156 passed, 17 xfailed);
  `run_gates.py repo --base origin/main` ALL GREEN; `check_module_size.py` within baseline;
  url4 `notebooks (examples/)` nbclient job reproduced locally: 3/3 ok.
