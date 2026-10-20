# Spec — resolve file refs in url4 (`url4-file-refs`)

Epic `OME-1529`. Contract: `OME-1534` conformance cases C1–C9, signed off by Kevin on 2026-10-13.
Port: the `OME-1538` bytes fetch (`fetch_bytes(request) -> FetchedBytes(body, media_type)`).
Trust checks (§5.4.2 policy, identity, attribution, `URL4-Auth-Token`) are `OME-1599`; only its
interim cross-node allowlist applies here.

## Today

- `src=/blob/sha256/<hex>` parses to `RelUrl` and is text-fetched: a PNG fails with
  `unsupported_content_type` (the `OME-1538` text guard), so C1 cannot resolve.
- `src=url4://n2/blob/sha256/<hex>` parses to `Url` and is text-fetched from any host: same failure,
  and no allowlist.
- `src=blob:sha256/<hex>` and `'blob:sha256/<hex>'` both parse to `Text`; the renderer quotes the
  bare one, so it never round-trips, and nothing resolves it.

## Contract

1. **AST.** A new leaf `BlobRef(value)` holds a bare `blob:<alg>/<id>` token, where `<alg>` is
   `[a-z0-9]+(-[a-z0-9]+)*` and `<id>` is `[A-Za-z0-9_-]+`. Only a bare value whose whole text has
   that shape becomes a `BlobRef`; anything else stays as today (`Text`, `Url`, …). A quoted
   `'blob:…'` stays `Text` (C4). `(blob:…)!x` is still a `ParseError` (C7); `src=` is required.
2. **Render.** `BlobRef` renders unquoted. In a `:` chain and as a bare source it takes `src=`
   (`img:src=blob:…`, `(src=blob:…)!x`), because the bare token is not value-shaped (C7);
   `img=blob:…` keeps the sugar. A `BlobRef` intent is refused (`intent_atom` never produces one).
3. **Which sources are file refs.** In a value position: a `BlobRef`; a `RelUrl` whose whole value
   is `/blob/sha256/<64 hex>`; a `Url` whose whole value is `url4://<authority>/blob/sha256/<64 hex>`.
   Every other `RelUrl` / `Url` lowers exactly as today.
4. **Resolution (node by node).** A file ref resolves at the node evaluating its expression level,
   through the bytes port (`fetch_bytes`; an adapter without it falls back to the text fetch,
   UTF-8 encoded, as the `OME-1538` bridge does):
   - `/blob/sha256/<hex>` → relative fetch of that path on the current node (C1).
   - `blob:sha256/<hex>` → relative fetch of `/blob/sha256/<hex>`: the evaluating node's own store (C3).
     Any other algorithm, or an id that is not 64 hex digits, cannot be held: `source_not_found`,
     permanent, with no I/O (C5).
   - `url4://<authority>/blob/sha256/<hex>` → a `url4`-kind fetch (§3.5), only when the run's io
     allows that authority (interim rule below); otherwise refused, permanent, with no I/O (C2).
   - The store not holding the bytes → `source_not_found`, permanent (C5). Adapters report it from
     `fetch_bytes`: HTTP 404/410, a `StaticIOLayer` miss, a node's `endpoint_not_found`.
   - **Integrity:** the bytes' sha256 must equal `<hex>` (case-insensitive), else
     `x.blob_digest_mismatch`, permanent. A content address that returns other content is refused.
5. **Payload.** Payloads stay `str` and refs travel as text (`OME-1534` point 4, `OME-1543`). A
   resolved ref is a `ResolvedBlob`: a `str` whose value is the ref exactly as written, carrying
   `body` (bytes), `media_type` and `digest`. Text consumers see the ref; the engine connector
   (`OME-1545`) takes the bytes from it without fetching again.
6. **Nested sources are never modified (C6).** A `RemoteExpr` / `RelExpr` context is forwarded as
   written: the outer node neither resolves nor rewrites a ref inside it.
7. **C8.** A resolved blob in collection position: a text media type (none, `text/*`, or one of the
   collection parser's declared types) is parsed as today's fetched text; anything else is
   `unsupported_content_type`, permanent.
8. **C9.** A model that cannot take the file is the engine's refusal (`OME-1545`/`OME-1548`); in url4
   a `process` hook raising `intent_error` surfaces as `intent_error`, the source having resolved.
9. **Interim allowlist (`OME-1599`).** The io adapter declares the allowed peers through the optional
   duck-typed capability `blob_peer_allowed(authority) -> bool`. `HttpIOLayer` and `StaticIOLayer`
   take `blob_peers=` (authorities, `host[:port]`, compared lower-case). An adapter without the
   capability allows **no** peer: fail closed. The run-wide bounded wrapper forwards it.
10. **Status.** A node answering with `source_not_found` replies HTTP 404 (permanent under C §13.2.1).

## Out of scope

The blob store and its routes (`OME-1540`), `data:` attachment and model refusal (`OME-1545`,
`OME-1548`), refs through fan-out/reduce (`OME-1543`), trust checks (`OME-1599`), fetch-once
pinning and size caps (`OME-1544`), wiring `blob_peers` into `Url4Node` / the CLI / the engine,
quoted-URI parsing (`OME-1597`).
