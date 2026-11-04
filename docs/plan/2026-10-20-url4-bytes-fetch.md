---
ticket: unfiled
spec: ../spec/2026-10-20-url4-bytes-fetch.md
date: 2026-10-20
stack: url4 (packages/url4)
branch: url4-bytes-fetch (renamed OME-N-<desc> at PR-open)
---

# Plan: url4 bytes fetch port

Paths under `packages/url4/`. Tests are append-only; new tests live in
`tests/unit/test_io_bytes_fetch.py`.

## U1 — Port and classifier (RED → GREEN)

- Tests: classifier table; `fetch_bytes` bridge prefers the capability and falls back to UTF-8.
- Code: `io/layer.py` `FetchedBytes`, `SupportsFetchBytes`, `fetch_bytes`, `is_text_media_type`;
  `core/errors.py` `UNSUPPORTED_CONTENT_TYPE`.

## U2 — HTTP adapter

- Tests (httpx `MockTransport`): PNG/PDF bytes identical; `Accept` from `accept` on both
  `fetch_bytes` and `fetch_ex`; none when unset; binary on `fetch`/`fetch_ex` refused permanent;
  text with charset unchanged; 404 on `fetch_bytes` still a permanent `ResolutionError`.
- Code: `io/http.py` — `_get(url, accept)`, `fetch_bytes`, a `_text(response)` guard.

## U3 — Static adapter and bounded wrapper

- Tests: bytes round-trip, str encode, refused binary on text path, text bytes decode, route via
  `fetch_bytes`; wrapper forwards only when supported.
- Code: `io/static.py`, `dag/_context.py`.

## U4 — Gates and live e2e

- `uv run .claude/scripts/run_gates.py url4`; engine stack gate as a regression check.
- e2e: `python -m http.server`-style fixture (logging `Accept`) serving PNG, PDF, text; fetch
  each via `HttpIOLayer`; sha256 equal; text unchanged; `Accept` in the log.
