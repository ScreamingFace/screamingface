---
ticket: OME-1538
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-20
---

# url4-bytes-fetch — Fetch url4 sources as bytes with their media type

Spec: `docs/spec/2026-10-20-url4-bytes-fetch.md`. Plan: `docs/plan/2026-10-20-url4-bytes-fetch.md`.
Epic `OME-1529`; blocker `OME-1534` is Done (point 4: the bytes port is internal, not a spec change).

## Intent

A PDF or PNG given as a url4 source is decoded with `response.text` and reaches the model as
mangled text, silently. Add an internal bytes fetch port returning `(bytes, media_type)` next to
the text fetch, make the HTTP and static adapters binary-safe, refuse to decode a binary media
type as text, and send `Accept` from `;accept=`. Engine attachment (Part G §26.2.3 `data:` URI)
is a later unit; `Payload` stays `str`.

## Planned changes

- `packages/url4/src/url4/io/layer.py` — `FetchedBytes`, `SupportsFetchBytes`, `fetch_bytes()` helper, `is_text_media_type()`.
- `packages/url4/src/url4/core/errors.py` — `ErrorCode.UNSUPPORTED_CONTENT_TYPE` (C §13.5.2).
- `packages/url4/src/url4/io/http.py` — `fetch_bytes`; `Accept` from `request.accept`; text paths refuse a binary type.
- `packages/url4/src/url4/io/static.py` — `fetch_map` takes `str | bytes`; `fetch_bytes`.
- `packages/url4/src/url4/dag/_context.py` — the bounded wrapper forwards `fetch_bytes`.
- `packages/url4/tests/unit/test_io_bytes_fetch.py` — new tests.

## Test plan

- HTTP: PNG/PDF bytes byte-identical with media type; text body bytes; `Accept` sent from `accept` on `fetch_bytes` and `fetch_ex`; no `Accept` override when `accept` is None; binary type on `fetch` / `fetch_ex` → `ResolutionError(unsupported_content_type, permanent)`; text with charset still decodes as today; HTTP errors still map.
- Static: bytes value round-trips; str value encodes UTF-8; binary bytes on text `fetch` → refused; text bytes decode; routes via `fetch_bytes`.
- Port helper: prefers `fetch_bytes`; old adapter falls back to UTF-8 of the text body + media type.
- Classifier table: None/text/*/json/xml/+json/charset → text; image/*, application/pdf, octet-stream → binary.
- Bounded wrapper exposes `fetch_bytes` only when the inner adapter has it.

## Acceptance

- PNG and PDF via HTTP adapter byte-identical (unit + live e2e sha256).
- `;accept=` reaches the request header (unit + e2e server log).
- Existing text and collection tests unchanged and green; `run_gates.py url4` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the port types, the bridge, the classifier and `require_text` live in a new
  `packages/url4/src/url4/io/media.py` instead of `io/layer.py`: `layer.py` is at its CI size cap
  (`scripts/check_module_size.py`) and must stay standard-library only. `dag/_context.py` may import
  only `io.layer` / `io.idempotency` (`tests/unit/test_layering.py`), so `BoundedIOLayer` forwards
  `fetch_bytes` duck-typed. Its two existing bounded forwarders were folded into one generic
  `_admit`, which removed two `# type: ignore` (suppression baseline lowered 5 → 3).
- **Commits:** see the PR (`OME-1538-url4-bytes-fetch`).
- **Gates:** `run_gates.py url4` ALL GATES GREEN (1154 unit tests in `tests/unit`, coverage floor 95%
  met; `io/layer.py` and `io/_text_guard.py` 100%). Regression: `run_gates.py screamingface-engine`
  ALL GATES GREEN.
- **Live e2e (2026-10-20):** local `http.server` fixture serving `digits.png` (4827), `zebra.pdf`
  (ZEBRA-4127) and a UTF-8 text file, fetched through the real `HttpIOLayer`: PNG and PDF sha256
  equal to the originals with media types `image/png` / `application/pdf`; text via `fetch` and
  `fetch_ex` equal to the file; the server log shows `Accept: image/png`, `application/pdf`,
  `text/plain` from the request's accept, and `*/*` when unset; `fetch_ex` on the PNG refused with
  `unsupported_content_type` (permanent). An expression `https://x/d;accept=text/plain` sends
  `Accept: text/plain` (unit test through `run`).
- **Deviations:** the module split above (CI-only ratchets the card's url4 `gates:` do not list:
  `check_module_size.py`, `check_suppressions.py`). Behaviour change by design: the text paths (`fetch`, `fetch_ex`) now refuse a
  binary media type (incl. `application/octet-stream`) instead of returning mojibake. `;accept=`
  is sent verbatim (no shorthand such as `csv` is expanded).
