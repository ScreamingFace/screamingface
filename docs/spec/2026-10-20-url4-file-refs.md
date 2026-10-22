# Spec — resolve file refs in url4 (`url4-file-refs`)

Epic `OME-1529`. Contract: `OME-1534` conformance cases C1–C9, signed off by Kevin on 2026-10-13.
Port: the `OME-1538` bytes fetch (`fetch_bytes(request) -> FetchedBytes(body, media_type)`).
Amended 2026-10-21 to #1450 spec §2 F1/F2 (owner decisions D1–D6): remote blobs are deferred from
v1 and a resolved file is a typed attachment, not a `str` subclass. Trust checks are `OME-1599`.

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
   - `url4://<authority>/blob/…` — ANY authority (including one naming this node), any path or
     query under `/blob` — is remote and fails `x.remote_blob_unsupported`, permanent, before any
     I/O (C2 in v1; F1 / D1). Only a bare `/blob/sha256/<hex>` path or a token is local.
   - The store not holding the bytes → `source_not_found`, permanent (C5). Adapters report it from
     `fetch_bytes`: HTTP 404/410, a `StaticIOLayer` miss, a node's `endpoint_not_found`.
   - **Integrity:** the bytes' sha256 must equal `<hex>` (case-insensitive), else
     `x.blob_digest_mismatch`, permanent. A content address that returns other content is refused.
5. **Payload and attachment (F2 / D2).** Payloads stay plain `str`; `resolve` yields the ref
   text exactly as written. The file is a typed `url4.dag.attachment.Attachment` — `digest`
   (`sha256:<hex>`), `media_type` (`application/octet-stream` when the adapter reports none),
   optional `filename` / `detail`, plus the verified `body` (out of `repr` and equality) — from
   `BlobRefNode.attachment(ctx)`. No bytes ride on a `str`; nothing scans strings. Building the
   run's ordered `attachments[]` and wiring it into model calls (D3, D5, D6) is `OME-1543`.
6. **Nested sources are never modified (C6).** A `RemoteExpr` / `RelExpr` context is forwarded as
   written: the outer node neither resolves nor rewrites a ref inside it.
7. **C8 / D4.** A blob in collection position (marked at lowering, from structure), used as text and not attached: a text media type (none, `text/*`, or one of the
   collection parser's declared types) is parsed as today's fetched text; anything else is
   `unsupported_content_type`, permanent.
8. **C9.** A model that cannot take the file is the engine's refusal (`OME-1545`/`OME-1548`); in url4
   a `process` hook raising `intent_error` surfaces as `intent_error`, the source having resolved.
9. **No remote fetch path.** There is no peer allowlist and no `url4://` bytes fetch in v1; a
   follow-up remote-blob spec must meet the F1 bar first.
10. **Status.** A node answering with `source_not_found` replies HTTP 404 (permanent under C §13.2.1).

## Out of scope

The blob store and its routes (`OME-1540`), `data:` attachment and model refusal (`OME-1545`,
`OME-1548`), the run's `attachments[]` and its wiring into model calls (`OME-1543`), trust checks
(`OME-1599`), size caps (`OME-1544`), remote blobs (a follow-up spec, F1), quoted-URI parsing
(`OME-1597`).
