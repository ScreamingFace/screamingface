---
ticket: OME-1545
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-28
finished: 2026-10-28
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
