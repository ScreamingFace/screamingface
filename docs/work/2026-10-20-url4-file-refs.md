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

## Amendment 2026-10-21 — align with #1450 F1/F2 (owner decisions D1–D6, Sergey)

**Intent.** Remove the remote `url4://` blob fetch and its `OME-1599` interim peer allowlist: in
v1 every `url4://<any authority>/blob/…` ref is remote and fails `x.remote_blob_unsupported`,
permanent, before any I/O (D1; replaces `x.blob_peer_not_allowed`). Replace the `ResolvedBlob`
`str` subclass with a typed `Attachment` value (digest `sha256:<hex>`, media type, optional
filename/detail; D2). Resolution stays at the evaluating node; `Payload` stays plain `str`.
Wiring attachments into model calls, the run's ordered `attachments[]`, D3/D5/D6 = `OME-1543`.

**Planned changes.**
- `core/errors.py` — `REMOTE_BLOB_UNSUPPORTED` replaces `BLOB_PEER_NOT_ALLOWED`.
- `core/blob_ref.py` — a remote ref is any `url4://<authority>/blob…` (any authority, query).
- `dag/attachment.py` (new) — the typed `Attachment` (F2 fields + the verified bytes).
- `dag/nodes/blob.py` — `BlobRefNode.attachment(ctx)` (the seam for `OME-1543`); `resolve`
  returns the ref text; collection mode (D4) set structurally at lowering, no `str` subclass.
- `dag/_lowering.py`, `dag/_descriptor.py` — mark a blob in collection / `*src` position.
- `dag/nodes/iteration.py` — revert the `collection_body` hook.
- `io/http.py`, `io/static.py`, `io/media.py`, `dag/_context.py` — drop `blob_peers`,
  `blob_peer_allowed`, `peer_set` and the no-redirect url4 path.
- Tests (this PR's own files only): `tests/unit/test_blob_refs.py`, `tests/spec/test_file_ref_conformance.py`.

**Test plan.** RED first: `url4://` any authority → `x.remote_blob_unsupported` with zero I/O
calls (unit + C2); `/blob/sha256/<hex>` → typed `Attachment` with `sha256:` digest and media
type, digest verified; mismatch → `x.blob_digest_mismatch`; payload is a plain `str`; a text
blob as a collection iterates (D4) and a PNG is C8.

**Outcome (amendment).**
- **Actual files:** as planned. `dag/_context.py`, `io/media.py`, `dag/nodes/iteration.py` are
  back to the `cba065be1` base (their only changes here were the allowlist / `collection_body`).
  `HttpIOLayer.fetch_bytes` keeps only the 404/410 → `source_not_found` typing; the no-redirect
  url4 path is gone with the remote fetch.
- **Gates:** `run_gates.py url4 --base cba065be1` (append-only vs the merge-base, NOT skipped)
  ALL GATES GREEN — 2065 passed, 17 xfailed, coverage 99%; `blob.py`, `attachment.py`,
  `blob_ref.py` 100%. `check_module_size.py` within baseline (`_lowering.py` 635/640),
  `check_suppressions.py` 3/3. Regression `run_gates.py screamingface-engine` green.
- **Deviations:** (1) the remote form is broadened: any `url4://<authority>/blob…` (userinfo,
  port, query, other algorithm) is `x.remote_blob_unsupported`, so no `url4://…/blob` URL can fall
  through to a web fetch; (2) `Attachment.media_type` defaults to `application/octet-stream` when
  the adapter reports none (F2 makes it required); (3) `resolve` still fetches and verifies the
  bytes and returns only the ref text — `OME-1543` collects attachments via
  `BlobRefNode.attachment` (one fetch per ref until it caches); (4) collection position (D4) is
  marked at lowering for a direct ref only: `$x*(…)` with `x` bound to a blob ref iterates the ref
  text (fails as a scalar collection) — structural, no string scanning, flagged for `OME-1543`.
- **Rebase on the #1478 head `cb13fa58e` (2026-10-22, after #1521):** `http.py` resolved onto the
  guarded `_get`/`_send`: the bytes path's `typed=True` (404/410 → `source_not_found`) is threaded
  `fetch_bytes` → `_get` → `_send`; the interim `blob_peers` / no-redirect `follow` were dropped
  as `703e3105d` intends (the intermediate commit carries them via `follow_redirects=` on
  `client.send`). Gates: `run_gates.py url4` ALL GATES GREEN; `check_module_size.py` /
  `check_suppressions.py` within baseline. Tests vs merge-base: new files only.

## Amendment 2026-10-26 — refuse remote-node calls in a node context (#1450 C6/F1b, owner decisions)

**Intent.** Spec #1450 F1b/C6: in v1 a `url4://` remote-node call (a remote expression,
`RemoteFetchNode`) is refused with `x.remote_node_unsupported`, permanent, before any I/O, until
node-to-node authentication is specified. Owner decisions (Sergey, 2026-10-26): the refusal applies
in a **node context** only: every evaluation a `Url4Node` runs, and everything a `Client(node=...)`
evaluates except the one outer hop it builds itself. Bare `url4.run()` keeps today's behaviour (so
`test_c6_nested_remote_expression_forwards_its_sources_unchanged` stays, as the bare-run contract).
Plain `url4://host/path` data fetches (`WebFetchNode`) are not refused here (transport guard).
Remote blob refs keep `x.remote_blob_unsupported`. The switch is private: no grammar, no
`run()`/`Client` option, not exported from `url4` / `url4.dag`.

**Planned changes.**
- `core/errors.py` — `REMOTE_NODE_UNSUPPORTED = "x.remote_node_unsupported"`.
- `dag/remote_nodes.py` (new) — the per-evaluation policy (a ContextVar): refuse all, or allow one
  `(authority, path)` hop once; `check_remote_node` raises the typed error.
- `dag/nodes/fetch.py` — `RemoteFetchNode.resolve` checks the policy first (before any I/O).
- `peer/server.py` — `Url4Node._run_text` evaluates under "refuse all".
- `peer/client.py` — a node-targeted evaluation allows exactly its own wrapper hop, once.
- Tests (new file only): `tests/unit/test_remote_node_refusal.py`.

**Test plan.** RED first: C6 through a `Url4Node` → `x.remote_node_unsupported`, permanent, no
fetch of any kind; `RemoteFetchNode` under the policy → refused with zero I/O; a `url4://` call
nested in a Client-wrapped expression is refused at the node; the Client's outer hop works; bare
`run()` still forwards; a relative call at a `Url4Node` still works; a remote blob ref under the
node policy still → `x.remote_blob_unsupported`; a plain `url4://host/path` fetch under the policy
is unaffected; the one-hop allowance is single-use and matches only its own authority/path.

**Outcome (amendment 2026-10-26).**
- **Actual files:** as planned: `core/errors.py`, `dag/remote_nodes.py` (new, 100% covered),
  `dag/nodes/fetch.py` (one check line + import), `peer/server.py`, `peer/client.py`,
  `tests/unit/test_remote_node_refusal.py` (new, 16 tests). No prior test changed;
  `test_c6_nested_remote_expression_forwards_its_sources_unchanged` stays as the bare-`run()`
  contract, so no test-change manifest.
- **Gates:** `run_gates.py url4` ALL GATES GREEN (append-only vs HEAD; 2288 passed, 17 xfailed);
  `check_module_size.py` within baseline (`peer/server.py` 315/315, `peer/client.py` 464/467,
  `dag/nodes/fetch.py` within cap); `check_suppressions.py` 3/3. Regression
  `run_gates.py screamingface-engine` ALL GATES GREEN.
- **Deviations:** (1) the policy is a ContextVar in `dag/remote_nodes.py`, not an
  `ExecutionContext` field: `dag/_context.py` and `peer/server.py` are at their size caps, and a
  per-evaluation ContextVar reaches every spawned task without a new constructor argument;
  (2) `peer/server.py` stayed at its cap by rewording two comments/docstrings (no code change);
  (3) the Client's allowance is single-use and exact on `(authority, path)`; no client-side
  intent form lowers to a `RemoteFetchNode` today (a parenthesised intent is text), so the
  nested-call refusal for a Client happens at the target node; (4) "before any I/O" means
  before the remote call's own I/O: deps of the `RemoteFetchNode` (e.g. a fetched intent)
  resolve first, as for any node; (5) a `url4://<own name>/…` remote expression at a node is
  refused too (spec: every `url4://` remote-node call); relative calls are unchanged.

## Amendment 2026-10-27 — generic content identifiers (design PR 31 review, finding 1)

**Intent.** HupBaHa's CHANGES_REQUESTED review of OpenMined/screamingface-design PR 31 (Part B
§5.4.4, 2026-10-27) found that #1482 recognised only lower-case `blob:<alg>/<id>`: another
namespace stayed `Text` (reaching an executor as text) and `blob:md5/…` was `source_not_found`
(indistinguishable from missing bytes). Owner decision (Sergey, 2026-10-27): implement generic
content IDs. The parser recognises every syntactically valid `<namespace>:<algorithm>/<digest>`
(Part B §8 `content-id`); v1 supports only `blob:sha256/<64 lowercase hex>`; any other
namespace or algorithm (case-sensitive) is permanent `unsupported_mode` before any I/O. The
digest is an opaque key: `.`/`..` are not digests (stay text). Quoted forms stay literal text.

**Planned changes.**
- `core/blob_ref.py` — the `content-id` regex; `BlobAddress.form` gains `"unsupported"`;
  no case-folding of the token digest.
- `dag/nodes/blob.py` — `unsupported` → `unsupported_mode`, permanent, before any I/O.
- `core/nodes.py` — `BlobRef` docstring (any content identifier).
- Tests: new `tests/spec/test_content_id_conformance.py`; this PR's own
  `tests/unit/test_blob_refs.py` cases that pinned the narrower shape change (see manifest).

**Test plan.** Other namespace, `blob:md5`, `blob:sha3-256`, `BLOB:`/`SHA256` → parse as
`BlobRef`, round-trip, run → `unsupported_mode` permanent with zero requests; upper-case hex →
`source_not_found` with zero requests; `.`/`..` digests → `Text`, no address; quoted → literal
text, never fetched; non-productions (`blob:/x`, `1x:…`, `a/b` digest) → `Text`.

**Outcome (amendment 2026-10-27).**
- **Actual files:** as planned: `core/blob_ref.py` (content-id regex, `unsupported` form, no
  digest case-folding), `dag/nodes/blob.py` (`unsupported_mode` check before any I/O),
  `core/nodes.py` (docstrings only), new `tests/spec/test_content_id_conformance.py` (34 cases).
- **Test-change manifest (this PR's own tests; none exists on `origin/main`):**
  `tests/unit/test_blob_refs.py` — `test_a_token_that_is_not_blob_shaped_stays_text` drops
  `blob:SHA256/abc`, `blob:sha256/a.b`, `blobs:sha256/abc` (now content IDs, covered by the
  conformance file); `test_upper_case_hex_is_looked_up_lower_case_and_kept_as_written` →
  `test_upper_case_hex_is_an_opaque_key_and_never_case_folded` (`source_not_found`, no I/O);
  `test_a_token_no_store_can_hold_is_source_not_found_without_io` drops `blob:md5/abc` (now
  `unsupported_mode`); `test_address_of_a_token_a_remote_ref_and_a_non_ref` uses lower-case hex.
- **Gates:** `run_gates.py url4 --base 506c09178` ALL GATES GREEN (2318 passed, 17 xfailed;
  `--base` = merge-base with `origin/main`, since the HEAD-based append-only check would flag this
  PR's own tests); `scripts/check_module_size.py` all capped modules within baseline;
  `scripts/check_suppressions.py` 3/3.
- **Deviations:** (1) upper-case sha256 hex is `source_not_found` (namespace and algorithm are
  supported; the opaque key is simply not held) — the previous lower-casing lookup is gone;
  (2) namespace/algorithm compare case-sensitively (`BLOB:`/`SHA256` → `unsupported_mode`);
  (3) the relative path form `/blob/sha256/<HEX>` is unchanged (implementation-defined mapping,
  §5.4.4); (4) `.`/`..` digests stay `Text` (outside the production), as before.
