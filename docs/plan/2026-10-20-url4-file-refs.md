# Plan — url4-file-refs

Spec: `docs/spec/2026-10-20-url4-file-refs.md`. Stack `url4` (`packages/url4`), TDD per step.
CI ratchets: `core/nodes.py`, `core/render.py`, `core/grammar.py`, `dag/_context.py` are within
1–5 lines of their size caps, so new logic goes to new modules and the capped files get only the
hooks (moving pure helpers out where a hook does not fit).

1. **Errors.** `ErrorCode.SOURCE_NOT_FOUND`, `X_BLOB_PEER_NOT_ALLOWED`, `X_BLOB_DIGEST_MISMATCH`;
   peer status 404 for `source_not_found`. Tests first.
2. **AST + grammar.** `core/blob_ref.py` (token/path regexes, `bare_value()`, render guard);
   `BlobRef` in `nodes.py`; `grammar._parse_bare` delegates. Tests: C3/C4/C7 parse, malformed stay `Text`.
3. **Render.** `BlobRef` renderer; `src=` for a bare source; intent refused. Tests: round trips.
4. **Adapters.** `blob_peers=` + `blob_peer_allowed` on `HttpIOLayer` / `StaticIOLayer`;
   `fetch_bytes` not-found → `source_not_found`; bounded wrapper forwards the capability.
5. **DAG.** `dag/nodes/blob.py` (`BlobRefNode`, `ResolvedBlob`); lowering for `BlobRef` and
   blob-shaped `RelUrl` / `Url`; collection boundary (C8). Tests: C1, C2, C3, C5, C6, C8, C9,
   digest mismatch, allowlist refusal without I/O.
6. **Conformance file** `tests/spec/test_file_ref_conformance.py`: C1–C9 by name.
7. **Gates** `run_gates.py url4` + `check_module_size.py` + `check_suppressions.py`; regression run of
   `screamingface-engine` (it imports `url4`).
8. **Live** two `Url4Node` processes on two ports (C6 over HTTP).
