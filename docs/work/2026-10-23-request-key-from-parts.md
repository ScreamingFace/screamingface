---
ticket: OME-1271   # PR 1a of the OME-1271 stack
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-23
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
