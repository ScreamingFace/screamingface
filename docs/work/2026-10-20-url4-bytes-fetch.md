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
- **Rebase on #1521 (2026-10-22):** rebased onto `506c09178` (url4 source guard). `http.py`
  resolved as the #1521 ledger prescribes: `_get(target, *, relative, accept=None)` translates
  `url4://` to `https`, builds the headers (`Idempotency-Key` + `Accept`) and calls
  `_send(url, headers or None, peer=peer, relative=relative)`; both helper blocks kept
  (`_trusted_origins`/`_read_capped`/`_buffered` and `_media_type`/`_text`). `fetch_bytes` goes
  through `_get`, so it inherits the destination guard, the total deadline and the size cap. New
  test `tests/unit/test_io_bytes_fetch_guard.py`: `fetch_bytes` to `169.254.169.254` (literal and
  via DNS) is refused with `x.source_destination_blocked`, nothing reaches the wire. Gates:
  `run_gates.py url4` ALL GATES GREEN; `check_module_size.py` / `check_suppressions.py` within baseline.

## Review round 2 (HupBaHa, 2026-10-22T13:47Z) — status: done

- **Planned:** (1) `io/media.py` parses `Content-Type` per RFC 9110 (token `/` token, quoted-string
  parameters, no new dependency); an invalid or comma-joined (duplicate-header) value is not text;
  `charset` makes only a non-binary `application/*` type text — `image/*`, `audio/*`, `video/*`,
  `font/*`, `model/*`, `multipart/*` and binary application types (octet-stream, pdf, zip, …) win;
  new `bare_media_type()` gives the bytes path one validated bare type or raises
  `unsupported_content_type`; `io/http.py` `_media_type` uses it. (2) `BoundedIOLayer._admit`
  forwards `**kwargs`. (3) `RemoteFetchNode.accept`, set by `_push_label`, sent on its `FetchRequest`.
- **Tests (new file, prior tests untouched):** `tests/unit/test_io_media_type_review.py`.
- **Outcome:** as planned. The parser is a `re.fullmatch` of the RFC 9110 media-type grammar
  (a hand scanner tripped ruff's return/branch limits). `HttpIOLayer._media_type(target, response)`
  goes through `bare_media_type`, so `fetch_bytes` and `fetch_ex` report one bare type or raise.
  Tests: `tests/unit/test_io_media_type_review.py` (45 cases; the five reviewer values on the
  classifier, `require_text`, both HTTP text paths and `fetch_bytes`; keyword calls through
  `BoundedIOLayer`; remote-expression `;accept=` lowering + wire + default). No prior test edited.
- **Gates:** `run_gates.py url4` ALL GATES GREEN (2160 passed, 17 xfailed; `io/media.py` 100%);
  `check_module_size.py` within baseline (`dag/_context.py` 453/455, `dag/nodes/fetch.py` 286/290);
  `check_suppressions.py` 3/3.
- **Deviations:** behaviour narrowed by design — `charset` now makes only a non-binary
  `application/*` type text (e.g. `message/*; charset=` is now refused, fail-closed);
  `StaticIOLayer.fetch_bytes` (a test double) still reports its configured media type verbatim.
- **ReDoS fix (security review of c9e01ca12):** the regex's overlapping `[ \t]*;[ \t]*` steps
  backtracked exponentially (`'text/plain' + '  ;  '*12 + ','`, 70 chars, took 10.9 s). Replaced
  by a linear hand scanner (every loop advances), and a Content-Type over 1 KiB is not one media
  type (only the first 1025 chars are ever scanned). Test: `tests/unit/test_io_media_type_redos.py`
  (six pathological headers incl. `'text/plain; a="' + '\\"'*50_000`, each < 100 ms; the 1 KiB
  boundary; quoted-pair and malformed-parameter cases). Gates green; `io/media.py` 100%.
