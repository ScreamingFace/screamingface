---
ticket: OME-1271   # PR 1a of the OME-1271 stack
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-23
finished: 2026-10-23
---

# request-key-from-parts — build the model request key from picture bytes, not raw JSON

## Intent

Cases will soon carry pictures inline as `data:` URIs inside the v2 candidate-input envelope. The
Engine's model request key (the join key grading accounting uses to match a judge call to the Case
that owns it) hashes the raw context JSON, so two encodings of the same picture (base64 line breaks,
padding, envelope key order, whitespace) would get two keys. Following the spec on PR #1450 (its
pictures-in-requests identity rule), a v2 context with a picture or file is keyed by its canonical
ordered part list: decoded-byte digests, media type, detail, filename, role, message index and
position, plus an adapter revision. A request with no picture or file keeps today's key byte for byte.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py` — a public
  `split_data_uri` so the key reads the same `data:` pattern the parser checks (one pattern).
- `apps/screamingface-engine/src/screamingface_engine/request_identity.py` — `canonical_request_parts`
  (envelope messages → canonical part list, reusable by OME-1679's Fusion synthesizer contexts),
  `NON_TEXT_PART_ADAPTER_REVISION`, and `model_request_key` keying a picture-bearing v2 context by parts.
- `apps/screamingface-engine/tests/unit/test_request_identity.py` — new.

## Test plan

- Text-only keys pinned to the literal values `upstream/main` produces (plain prompt, v1 envelope,
  Fusion-shaped JSON text, no context).
- Equal picture bytes under different base64 line breaks / padding, envelope key order or whitespace
  → one key.
- Different media type, detail, filename, role or position → different keys.
- Adapter revision moves a picture-bearing key and leaves text keys alone.
- `operation_call_identity` and `register_grading_request` record the same key for one picture call.
- Undecodable base64 and an envelope the parser refuses: the key falls back to today's raw form
  (the connector owns the refusal).

## Acceptance

- Every existing text key and golden unchanged (existing request-key tests green, pinned literals).
- A picture-bearing v2 context keys by decoded bytes, not by base64 spelling.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the OME-1271 mirror `docs/tasks/2026-10-23-OME-1271-images-in-cases.md`.
- **Commits:** e3bfbd046 — feat(screamingface-engine): key picture requests by canonical parts, not base64 spelling
- **Gates:** relevant tests only — `test_request_identity.py` 17, `test_candidate_input.py` 45,
  `test_grading_accounting.py` 9, `test_operation_capture_executor.py` 7,
  `test_request_accounting_boundaries.py` 1 (all pass); `inspect/test_judge_seed_per_pass.py` +
  `inspect/test_concurrent_judge_booking.py` 15 pass with the inspect extra (`uv run --isolated`);
  ruff check + format and pyright clean on touched files; layering gate OK. Two mutation checks
  (hash base64 text instead of bytes; drop the adapter revision) each fail the matching test.
- **Deviations:** the model-result cache and frozen copy are keyed by the gateway, not by this
  Engine key (the Engine key is the grading-accounting join key), so this PR does not change the
  gateway cache's view of a picture; flagged as an open question on the PR.
- **Review round 1 (head 6c254254c):**
  - The docstring and a test comment said undecodable base64 is refused before any model call. It
    is not: the parser, the connector and the gateway pass base64 on verbatim, so only the provider
    rejects it, after spend. Both now say what happens; the key still falls back to the raw text.
  - Import cost: the envelope module loads the whole `benchmarks` package and url4. Cumulative
    `python -X importtime` for `screamingface_engine.request_identity`, three runs each: `main`
    17.4-17.9 ms, this branch before the fix 90-120 ms, after 17.7-20.4 ms. Fixed with
    function-local imports behind a "does the context open a JSON object" check, pinned by a
    subprocess test. A JSON-object text context (v1 envelope, Fusion JSON) still loads the module
    once, on its first key.
  - The exact canonical shape now covers a PDF part with a filename (OME-1679 consumes it).
- **Open follow-up:** the connector should refuse undecodable base64 in a v2 Case by name, before
  any model call, instead of leaving it to the provider.
