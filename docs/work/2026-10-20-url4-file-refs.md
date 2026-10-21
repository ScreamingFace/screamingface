---
ticket: OME-1539
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-20
---

# url4-file-refs — Resolve file refs in url4: /blob/sha256 paths, url4:// across nodes, blob:sha256 tokens

Spec: `docs/spec/2026-10-20-url4-file-refs.md`. Plan: `docs/plan/2026-10-20-url4-file-refs.md`.
Epic `OME-1529`; contract = `OME-1534` conformance cases C1–C9 (Kevin, 2026-10-13). Built on the
`OME-1538` bytes port (branch `OME-1538-url4-bytes-fetch`).

## Intent

A url4 source naming a content-addressed file (`/blob/sha256/<hex>`, `url4://<node>/blob/sha256/<hex>`,
bare `blob:sha256/<hex>`) is today either text-fetched (a PNG fails with `unsupported_content_type`)
or, for the bare token, parsed as quoted text and never resolved. Resolve all three through the
bytes port at the evaluating node, keep the bare token distinct from quoted text in the AST, and
leave nested sources untouched. Trust checks stay with `OME-1599`; its interim cross-node allowlist
applies here, fail closed.

## Planned changes

- `packages/url4/src/url4/core/nodes.py` — `BlobRef` in the `Node` union.
- `packages/url4/src/url4/core/_blob_ref.py` (new) — the token/path grammar for blob refs (parse + render guard).
- `packages/url4/src/url4/core/grammar.py` — a bare `blob:<alg>/<id>` value parses to `BlobRef`.
- `packages/url4/src/url4/core/render.py` (+ a split-out helper module to stay under the size cap) — `BlobRef` renders unquoted; `src=` where the chain needs it.
- `packages/url4/src/url4/core/errors.py` — `SOURCE_NOT_FOUND` (C §13.2.5) + implementation codes for the interim allowlist and a digest mismatch.
- `packages/url4/src/url4/dag/nodes/blob.py` (new) — `BlobRefNode` + `ResolvedBlob` payload.
- `packages/url4/src/url4/dag/_lowering.py` — `BlobRef`, blob-shaped `RelUrl`/`Url` lower to `BlobRefNode`.
- `packages/url4/src/url4/dag/_context.py` — the bounded wrapper forwards `blob_peer_allowed`.
- `packages/url4/src/url4/dag/nodes/iteration.py` — a resolved blob in collection position: text body parsed, binary refused (C8).
- `packages/url4/src/url4/io/http.py`, `io/static.py` — `blob_peers=` allowlist; `fetch_bytes` not-found → `source_not_found`.
- `packages/url4/src/url4/peer/_http.py` — `source_not_found` → 404.
- Tests: `tests/unit/test_blob_refs.py`, `tests/spec/test_file_ref_conformance.py` (C1–C9).

## Test plan

- Parse/render: bare token → `BlobRef`; quoted → `Text` (C4); `(blob:…)` → ParseError (C7); round-trip unquoted, incl. `img:src=`, `img=`, weighted descriptor; `BlobRef` intent refused by render; malformed tokens stay `Text`.
- Resolution (fake store via `StaticIOLayer`): `/blob/sha256/<hex>` (C1), bare token (C3), `url4://n2/blob/…` with allowlist (C2), not allowlisted → refused without I/O, missing → `source_not_found` permanent (C5), digest mismatch refused, non-sha256 / malformed id → `source_not_found` without I/O.
- Nested: `url4://n2/v1(img:src=blob:…)!…` forwards the inner context byte-identical, no store lookup on the outer node (C6).
- C8: binary blob as a collection → `unsupported_content_type`; C9: model hook raising `intent_error` after a resolved blob → `intent_error`.
- Invariant: other relative URIs and text-only expressions unchanged (existing suite green, untouched).

## Acceptance

- C1–C9 executable and green; `run_gates.py url4` green; CI ratchets (module size, suppressions) green.
- Live: two `Url4Node` processes, nested expression addressed to node 2 reaches it with its blob ref unchanged and node 2 resolves it from its own store.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: the token grammar lives in a PUBLIC `core/blob_ref.py`
  (not `_blob_ref.py`: the private-import ratchet `tests/unit/test_private_imports.py` counts a
  `dag` → `core._x` crossing); `core/_directives.py` (iteration directive types moved out of
  `nodes.py`, re-exported unchanged) and `core/_render_values.py` (weight/budget/number/quote
  renderers moved out of `render.py`, `builders.py` imports them) so `nodes.py` (cap 346) and
  `render.py` (cap 676) could take the new hooks; `dag/semantics/collection.py` gains
  `DECLARED_MEDIA_TYPES`; `io/media.py` gains `peer_set`. `BlobRef` is NOT exported from top-level
  `url4` (the export count is pinned by a prior test); it is `url4.core.nodes.BlobRef`.
- **Commits:** see the PR (`OME-1539-url4-file-refs`).
- **Gates:** `run_gates.py url4` ALL GATES GREEN (2057 passed, 17 xfailed; coverage 99%, new
  modules 100%). CI ratchets: `check_module_size.py` all within baseline (`dag/_context.py` 455/455),
  `check_suppressions.py` 3/3. Regression: `run_gates.py screamingface-engine` ALL GATES GREEN.
- **Conformance:** C1–C9 executable in `tests/spec/test_file_ref_conformance.py`, all green.
- **Live e2e (2026-10-20):** two `Url4Node` processes (ports 4761/4762, uvicorn; harness maps
  `url4://` to `http://` because the local nodes speak plain HTTP). `GET n1/v1?q=(url4://n2/v1(img:src=blob:sha256/<hex>)!'Describe')!'Summarize'`
  → 200; n2's raw query was `q=(img:src=blob:sha256/<hex>)!%27Describe%27` (the ref unchanged), n2
  resolved it from its own store (data route) and its model saw `img: blob:sha256/<hex>`. Missing
  digest: n2 answered 404 `source_not_found` (C5); n1 relayed it as 502 `resolution_failed`
  (the peer client does not carry a remote error code; pre-existing). `url4://n2/blob/…` at n1 →
  `x.blob_peer_not_allowed` (a `Url4Node` declares no allowlist: fail closed). Quoted
  `'blob:sha256/abc'` at n2 → literal text (C4).
- **Deviations:** (1) the module splits above, forced by the CI size ratchets; (2) HTTP
  `fetch_bytes` refuses to follow a redirect for a `url4://` target (permanent error), so an
  allowlisted node cannot bounce the fetch elsewhere — the safe option for the interim rule;
  (3) `source_not_found` is typed only on the bytes path (HTTP 404/410, static miss, a node's
  `endpoint_not_found` for its own store path); the text path's 404 keeps `resolution_failed`;
  (4) peer status: `source_not_found` → 404; (5) `;accept=` is not applied to blob refs
  (content-addressed; YAGNI).
- **Stack check (2026-10-21):** fetched; this branch already sits on the current
  `OME-1538-url4-bytes-fetch` head `cba065be1` (merge-base = that head), so no rebase was needed.
  `run_gates.py url4` ALL GATES GREEN (append-only included). Own commits on top of #1478:
  `87b64b489` (feat) and the ledger/mirror docs commits; #1478's are `527935946`, `cba065be1`.
  `git merge-tree origin/main HEAD` is clean (main has not touched `packages/url4` since the
  #1478 base). After #1478 squash-merges: `git rebase --onto origin/main cba065be1`.
