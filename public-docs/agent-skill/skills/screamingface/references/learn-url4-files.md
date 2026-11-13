# Files in url4

Source: https://docs.screamingface.ai/learn/url4-files

Images and PDFs as url4 sources: file URLs, sha256 blob refs, what v1 refuses, and the limits.

> **Partly unreleased, partly proposed.** This page follows the file-input spec, merged with [#1450](https://github.com/ScreamingFace/screamingface/pull/1450) as a **draft**. Kevin's approval of its url4 wire changes (review rounds 7 to 10: the `;accept=` opt-in, the literal and model-free rules, and the new `x.*` error codes) is still pending, so those parts may change. Much of the code is not merged yet. Each section says where its behaviour stands: *on main* (merged, not in any `url4` release), *lands with #N* (an open pull request), or *proposed* (in the draft spec, no code yet).  
>   
> `pip install url4` installs **1.4.1**, the latest version on PyPI. The repository also has `url4-v1.5.0` and `url4-v1.5.1` GitHub releases (tags only, 2026-08-27); neither was published to PyPI. Everything marked *on main* here merged after them.

A [url4](learn-url4.md) source has always resolved to text. v1 of file input lets a source be an image or a PDF that reaches the model as a file, not as garbled text. The expression stays a string: files travel beside it, never inside it.

A file enters a run in one of two ways:

-   **A url4 source:** an `https://` URL whose `;accept=` is exactly one attachment type, or a `sha256` blob ref. Both are resolved by the node that evaluates the expression.
-   **A benchmark Case:** pictures written inline in the Case itself. Case media does not use the url4 attachment-source syntax or manifest; the Case still flows through the Cases route and url4 execution (see [Benchmark Cases](#cases)).

## A file URL as a source

*Proposed (OME-1543), not on main.* Everything in this section up to *On main today* is in the draft spec only: on main, the examples below attach nothing.

```
(https://example.org/chart.png;accept=image/png)!'Describe the chart'
```

An `https://` source becomes an **attachment source** only when its `;accept=` is **exactly one** lower-case type from the attachment types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `application/pdf`. There are no wildcards (`image/*`) and no lists: a url4 value admits neither `*` nor a comma. There is no new syntax: `;accept=` is the existing per-source annotation. `src=` does not mark an attachment, because `(src=https://a)` and `(https://a)` parse to the same source.

```
(https://example.org/notes.md)!'Summarize'                      # text source, as today
(https://example.org/data.json;accept=application/json)!'Sum'   # text source: not an attachment type
(https://example.org/scan.pdf;accept=application/pdf)!'Read'    # attachment source
(https://example.org/a.png;accept=image/png)!'Describe'         # attachment source
```

```
# x.source_not_static: the rows come from a model call
((https://rows)!'Produce JSON rows')*(https://files/static.png;accept=image/png)!'Use $item'
```

-   **Every other `https://` source is a text source**, read exactly as today: no `;accept=`, or any value that is not one of the attachment types (`text/csv`, `application/json`, …). It is fetched lazily, each occurrence under its own `;optional`, `;t=` and `;retry=`, and never attached. An expression with no attachment source behaves byte for byte as it does today.
-   **Fetched before the first model call.** The run first resolves its non-model collection inputs, then fetches every attachment source those rows actually reach, once each, and builds the attachment manifest. An iteration over zero rows fetches nothing. Occurrences with the same URL, `;accept=` and guard policy share one fetch and yield one attachment, placed at their first occurrence in the expression, never in completion order.
-   **Then frozen.** The bytes are hashed and stored for the run, and the list of attachments is fixed: every node sees the same list, nothing is fetched, re-fetched, added or reordered after the first model call, and a retry reuses it. Each model call sends the attachments as file parts first, then the text.
-   **The response type decides, no sniffing.** The response's `Content-Type`, bare and lower-cased, must **equal** the requested `;accept=` type: a `;accept=image/png` source answered with `image/jpeg` fails. A different or missing type fails the source with `unsupported_content_type`. A failed `;optional` attachment source is left out; a required one fails the run before any model call.
-   **Literal targets only.** An attachment source's URL and `;accept=` must both be literal in the expression. A row-substituted, variable (`src=$item;accept=image/png`), model-derived or fetched-body-derived URL is refused with `x.source_not_static` before any fetch. Attachment URLs taken from collection rows are deferred (OME-1748). Text sources may still be dynamic.
-   **Model-free reachability.** An attachment source inside an iteration whose collection depends on a model call (a processed group, a model call, a remote expression, a nested model-dependent iteration, or a binding to one) is refused with `x.source_not_static` before any I/O, even when that collection would be empty. Whether it is reached must be known before the first model call.

*On main today* there are no attachments: every `https://` source is read as text. *Lands with [#1478](https://github.com/ScreamingFace/screamingface/pull/1478):* the text path refuses a binary body with `unsupported_content_type` instead of decoding it.

### The transport guard

*On main ([#1521](https://github.com/ScreamingFace/screamingface/pull/1521)).* Every source fetch through url4's `HttpIOLayer` passes one destination guard, text and file sources alike:

-   `https` only. `http` is a configuration switch, off by default.
-   DNS is resolved first. Loopback, private, link-local (including the cloud metadata address `169.254.169.254`), CGNAT, unspecified, multicast and reserved addresses are refused, as are IPv6 forms that embed them. The connection goes to the vetted IP, so a second DNS answer cannot redirect it.
-   At most 3 redirects. Every hop is checked by the same rules, and a hop from `https` to `http` is refused.
-   A streaming cap on decoded bytes (20 MiB by default) that aborts mid-stream, a connect timeout and one total deadline for the whole fetch.
-   Proxy environment variables are ignored.
-   *On main ([#1605](https://github.com/ScreamingFace/screamingface/pull/1605)):* a URL with embedded credentials (userinfo, as in `https://user:pass@host/…`) is refused before any DNS lookup or connection, and so is a redirect hop whose `Location` carries them. The credentials are never sent.

```python
from url4.io.http import HttpIOLayer, SourceGuard

# The defaults, spelled out. HttpIOLayer() alone uses exactly these.
io = HttpIOLayer(
    guard=SourceGuard(
        allow_http=False,         # https only
        allow_loopback=False,     # test/dev escape hatch, loopback only
        max_redirects=3,
        max_bytes=20 * 1024 * 1024,   # decoded bytes, aborted mid-stream
        connect_timeout=10.0,
        total_timeout=60.0,       # the whole fetch, redirects included
    )
)
```

An `HttpIOLayer` built on a client you inject keeps only the size cap: you chose that client's destinations and timeouts.

## Blob refs

A blob ref names a file by the sha256 of its bytes. v1 has two local forms, both read from the evaluating node's own store (*lands with #1482*, see below):

```
(img:src=/blob/sha256/<hex>)!'Describe'    # local path on the evaluating node
(img:src=blob:sha256/<hex>)!'Describe'     # local bare token, same store
```

These forms do not resolve to a blob:

```
(img:'blob:sha256/<hex>')!'Describe'                 # quoted: plain text, never resolved
(blob:sha256/<hex>)!'Describe'                       # ParseError: a bare token needs src=
(img:src=url4://n2.example/blob/sha256/<hex>)!'d'    # remote blob: refused in v1
```

-   `/blob/sha256/<hex>` is a relative path. `blob:sha256/<hex>` is a bare token and needs `src=`.
-   The bytes are checked against the digest on every read. A mismatch is `x.blob_digest_mismatch`, permanent.
-   A digest the node does not hold is `source_not_found`. Under the spec, so is a digest stored for another run or tenant: a digest is not a bearer capability.

*Lands with [#1482](https://github.com/ScreamingFace/screamingface/pull/1482):* the `blob:` token, resolution at the evaluating node, the digest check and the remote-blob refusal. *On main:* the `ParseError` for a bare token without `src=`. *Proposed:* the run-scoped store and handing the verified bytes to the model. Until those land, a resolved ref reaches a model route as its text.

**Uploading a blob is coming.** There is no Python client API for putting a file into a node's blob store yet.

## Not in v1

-   **Remote blobs.** Every `url4://<node>/blob/…` ref fails with `x.remote_blob_unsupported`, permanent, before any network I/O, whatever the authority (the evaluating node's own name included). *Lands with #1482.*
-   **Remote-node calls.** A nested expression addressed to another node, `(url4://n2.example/v1(…)!'…')!'…'`, is refused until node-to-node authentication is specified. *Lands with #1482:* the code is `x.remote_node_unsupported`, permanent, before any I/O, wherever a node evaluates: every expression a `Url4Node` runs, and anything nested inside a `Client(node=…)` call (the client's own hop to its node still goes through). A bare library `url4.run()` and plain `url4://host/path` data fetches are not affected. *On main today:* the guard refuses it as `x.source_destination_blocked`, because its peer allowlist is empty by default.
-   **`data:` URIs in an expression.** Unquoted, the `;` and `,` split it and it is a `ParseError`; quoted, it is plain text. Inline `data:` belongs in Case envelopes only.

## Benchmark Cases

*On main ([#1507](https://github.com/ScreamingFace/screamingface/pull/1507)).* A Case with pictures uses the candidate-input envelope `screamingface.candidate-input.v2`. Its parts are OpenAI content parts: `image_url` (PNG, JPEG, GIF or WebP), as a `data:` URI, in user messages only. A text-only Case stays v1. Benchmark files are built into the benchmark image, so a Case never fetches anything at run time.

Case media does not use the url4 attachment-source syntax or the attachment manifest: the parts travel inside the envelope. The Case itself still runs through the Cases route and url4 execution.

*Not in v1:* PDF Case parts. The v2 schema reserves a `file` part (`application/pdf` only) for later, but v1 imports and executes pictures only, and the importer refuses a PDF by name.

## Limits

| Limit | Value | Status |
| --- | --- | --- |
| Gateway request body | 8 MiB (8,388,608 bytes), `AIGW_MAX_REQUEST_BYTES`. Over it: 413 `request_too_large`, before any upstream spend. | on main (#1479) |
| Pictures per Case | at most 20, refused at import by name | on main (#1554) |
| Case size with pictures inline | at most 8,000,000 bytes, leaving room under the gateway cap | on main (#1554) |
| url4 attachments per run | at most 20, counted over the whole attachment list: every local blob ref plus every `https://` attachment. Over it: `x.attachments_too_many`, before any model call. | proposed (OME-1543) |
| url4 attachment bytes per run | at most 8,000,000 decoded bytes over the same whole list. Over it: `x.attachments_too_large`, before any model call. | proposed (OME-1543) |
| One fetched source | 20 MiB decoded, by default (`SourceGuard.max_bytes`) | on main (#1521) |

There is no per-picture limit.

## Which models take files

*On main ([#1451](https://github.com/ScreamingFace/screamingface/pull/1451)).* Each row of the gateway's `/v1/models` carries `input_modalities`, a subset of `text`, `image` and `pdf`, always starting with `text`. When the gateway has no evidence for a model, the row says `["text"]`: unknown never means vision.

```
GET /v1/models

{"id": "<provider>/<model>", ..., "input_modalities": ["text", "image", "pdf"]}
{"id": "<provider>/<model>", ..., "input_modalities": ["text"]}
```

A part a model cannot take is refused loudly, never dropped:

-   *On main.* The gateway takes an image or a PDF as a `data:` URI and never fetches a URL itself. The one exception is Codex, which forwards an `https` image URL for OpenAI to fetch. Where a provider adapter cannot carry a part (a PDF to Ollama, media in an Anthropic system prompt), it answers 422 `unsupported_content_part` before dispatch. Not retryable.
-   *Proposed.* The engine checks `input_modalities` at admission and refuses a blind model by name with `intent_error`, before any spend.

## Errors

| Code | When | Status |
| --- | --- | --- |
| `x.source_destination_blocked` | Disallowed scheme, a refused address on any hop, an `https` to `http` redirect, or a `url4://` peer off the allowlist. Permanent. | on main; code proposed |
| `x.source_redirect_limit` | More redirects than the limit (default 3). Permanent. | on main; code proposed |
| `x.source_too_large` | The decoded body passed the cap. Permanent. | on main; code proposed |
| `x.source_timeout` | Connect timeout, or the total deadline across all hops. Retryable. | on main; code proposed |
| `unsupported_content_type` | A binary body on a text path (lands with #1478). On an attachment source: a `Content-Type` that is missing or not equal to its `;accept=` type (proposed, OME-1543). Permanent. | lands with #1478; proposed |
| `x.source_not_static` | An attachment source whose URL or `;accept=` is not literal, or that sits in an iteration whose collection depends on a model call. Permanent, before any fetch or model call. | proposed (OME-1543) |
| `x.attachments_too_many` | More than 20 url4 attachments in one run. Permanent, before any model call. | proposed (OME-1543) |
| `x.attachments_too_large` | More than 8,000,000 decoded bytes of url4 attachments in one run. Permanent, before any model call. | proposed (OME-1543) |
| `source_not_found` | The node does not hold the blob. Permanent. | lands with #1482 |
| `x.blob_digest_mismatch` | The bytes do not hash to the ref's sha256. Permanent. | lands with #1482; code proposed |
| `x.remote_blob_unsupported` | Any `url4://…/blob/…` ref. Permanent, no I/O. | lands with #1482; code proposed |
| `x.remote_node_unsupported` | A `url4://` remote-node call in a node context (`Url4Node`, or nested in a `Client` call). Permanent, no I/O. | lands with #1482; code proposed |
| `request_too_large` | Gateway body over 8 MiB. HTTP 413. | on main |
| `unsupported_content_part` | The provider adapter cannot carry the part. HTTP 422. | on main |

Codes with the `x.` prefix are implementation codes, and every one of them is **proposed**: Kevin's url4 wire approval of the draft spec is still pending, so a name or status may change. The `x.source_*` codes are already raised by the code on main. They stay prefixed until the url4 spec adopts them.

## Where the code lives

-   [`packages/url4/src/url4/io/_source_policy.py`](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/src/url4/io/_source_policy.py): the guard's rules and `SourceGuard`.
-   [`packages/url4/src/url4/core/errors.py`](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/src/url4/core/errors.py): the url4 error codes.
-   [`apps/aigateway/src/aigateway/core/input_modalities.py`](https://github.com/ScreamingFace/screamingface/blob/main/apps/aigateway/src/aigateway/core/input_modalities.py) and [`content_parts.py`](https://github.com/ScreamingFace/screamingface/blob/main/apps/aigateway/src/aigateway/core/content_parts.py): modalities and the part gate.
