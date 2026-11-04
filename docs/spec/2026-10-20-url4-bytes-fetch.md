# Spec — url4 bytes fetch port (`url4-bytes-fetch`)

Epic `OME-1529`. Decision basis: `OME-1534` point 4 ("the IOLayer gains a bytes fetch returning
`(bytes, media_type)`; `Payload` stays `str`") and conformance case C8
(`unsupported_content_type`, C §13.5.2). Internal port only: no grammar, wire or public-API change.

## Today

- `HttpIOLayer.fetch` / `fetch_ex` return `response.text` for every response
  (`packages/url4/src/url4/io/http.py`), so a PNG or PDF is decoded into mojibake.
- `FetchResult.body` is `str` (`io/layer.py`).
- `;accept=` is lowered into `FetchRequest.accept` (`dag/nodes/fetch.py`) but no adapter sends it.

## Contract

1. **Port.** `url4.io.media` (beside the `url4.io.layer` port, which is at its size cap) gains `FetchedBytes(body: bytes, media_type: str | None)`, the
   optional capability `SupportsFetchBytes.fetch_bytes(request) -> FetchedBytes`, and the bridge
   `fetch_bytes(io, request)`: it calls `fetch_bytes` when the adapter has it, otherwise
   `fetch_result` and UTF-8-encodes the text body (an old adapter could only ever give text).
   Not re-exported from `url4` (the top-level API is unchanged).
2. **Text vs binary.** `is_text_media_type(content_type)`: text when the type is absent,
   `text/*`, carries a `charset` parameter, is a JSON/XML/YAML/JS/ndjson/form/TOML/SQL/GraphQL
   application type, or has a `+json`/`+xml`/`+yaml` suffix. Everything else is binary
   (`image/*`, `audio/*`, `video/*`, `application/pdf`, `application/octet-stream`, …).
3. **Text path unchanged for text.** `fetch` / `fetch_ex` on a text type return exactly what
   they return today (`response.text`).
4. **Binary never goes through `.text`.** `fetch` / `fetch_ex` on a binary type raise
   `ResolutionError(code="unsupported_content_type", permanent=True)` (C8) instead of decoding.
   Callers that can handle files use `fetch_bytes`.
5. **Bytes path.** `HttpIOLayer.fetch_bytes` returns `response.content` unmodified plus the
   bare media type (parameters stripped, lower-cased), with the same error mapping,
   idempotency and redirect behaviour as the text path.
6. **Accept.** When `FetchRequest.accept` is set, `fetch_ex` and `fetch_bytes` send it as the
   `Accept` header verbatim. Unset → no header added (httpx default).
7. **Static adapter.** `fetch_map` values may be `str` or `bytes`. `fetch_bytes` returns bytes
   as-is and UTF-8-encodes strings and route results. A `bytes` value with a text media type
   decodes as UTF-8 on the text path; with a binary type it is refused as in (4).
8. **Concurrency bound.** The run's bounded I/O wrapper forwards `fetch_bytes` under the same
   semaphore, only when the inner adapter provides it.

## Out of scope

Engine attachment of fetched files as `data:` URIs (Part G §26.2.3), blob refs (`OME-1539`),
fetch-once pinning and the SSRF guard (`OME-1544`), size caps, and the peer node's own
`fetch_bytes` (it falls back through the bridge).
