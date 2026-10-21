<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_BLOB = 'https://github.com/ScreamingFace/screamingface/blob/main'
const GH_PR = 'https://github.com/ScreamingFace/screamingface/pull'

const bytesFetch = `import asyncio
from url4 import FetchRequest, StaticIOLayer
from url4.io.media import fetch_bytes

png = open("cat.png", "rb").read()
io = StaticIOLayer(
    fetch_map={"https://x/cat.png": png},          # str for text, bytes for a binary source
    media_types={"https://x/cat.png": "image/png"},
)

got = asyncio.run(fetch_bytes(io, FetchRequest("https://x/cat.png")))
got.body == png      # True: the bytes exactly as served
got.media_type       # 'image/png'

asyncio.run(io.fetch("https://x/cat.png", relative=False))
# ResolutionError: code='unsupported_content_type', permanent=True`

const refForms = `(img:src=/blob/sha256/<hex>)!'Describe'              # path on the evaluating node
(img:src=blob:sha256/<hex>)!'Describe'               # bare token, from the node's own store
('blob:sha256/<hex>')!'Describe'                     # quoted: plain text, never resolved
(blob:sha256/<hex>)!'Describe'                       # ParseError: a bare token needs src=
(img:src=url4://n2.example/blob/sha256/<hex>)!'d'    # another node: not supported in v1`

const refRun = `import hashlib
import url4

png = open("cat.png", "rb").read()
digest = hashlib.sha256(png).hexdigest()

io = url4.StaticIOLayer(
    fetch_map={f"/blob/sha256/{digest}": png},
    media_types={f"/blob/sha256/{digest}": "image/png"},
    routes={"/m": lambda context, intent: "ok"},
)
url4.evaluate_sync(f"(img:src=blob:sha256/{digest})!'Describe'", io=io)
# The ref resolves and its sha256 is checked. The route still sees the ref text,
# not the image: handing the bytes to a model is a later unit.`
</script>

<template>
  <DocLayout
    title="Files in url4"
    description="How url4 fetches a source as bytes, names a file by its sha256, and what v1 does not do yet."
    :navigation="navigation"
  >
    <blockquote>
      <strong>Draft: not released yet.</strong> Most of this page describes code in two open pull
      requests. Each section says which one it lands with:
      <a :href="`${GH_PR}/1478`" target="_blank" rel="noopener">#1478</a> (fetch sources as bytes)
      and <a :href="`${GH_PR}/1482`" target="_blank" rel="noopener">#1482</a> (blob file refs, built
      on #1478). Until they merge, a published <code>url4</code> does none of it. Sections marked
      <em>on main</em> describe code that has already merged.
    </blockquote>

    <p>
      A <RouterLink to="/learn/url4">url4</RouterLink> source has always resolved to text. An image
      or a PDF needs its exact bytes and its media type instead, so it can reach a model as a file
      and not as garbled text. This page covers the two pieces that make that possible: fetching a
      source as bytes, and naming a file by its content hash.
    </p>

    <h2>Text or bytes</h2>

    <p>
      <em>Lands with #1478.</em> One rule, <code>url4.io.media.is_text_media_type</code>, decides
      whether a <code>Content-Type</code> is text. These count as text: no type at all,
      <code>text/*</code>, any type that declares a <code>charset</code>, the JSON, XML, YAML,
      JavaScript, ndjson and form types, and the <code>+json</code>, <code>+xml</code> and
      <code>+yaml</code> suffixes. Everything else is binary, including <code>image/*</code>,
      <code>application/pdf</code> and <code>application/octet-stream</code>.
    </p>

    <p>
      The text paths (<code>fetch</code>, <code>fetch_ex</code>) of <code>HttpIOLayer</code> and
      <code>StaticIOLayer</code> check this rule before they decode. A binary body raises
      <code>ResolutionError</code> with code <code>unsupported_content_type</code>, and the error is
      permanent, so a retry will not help. A text body comes back exactly as before.
    </p>

    <blockquote>
      <strong>Behaviour change.</strong> A text file served as
      <code>application/octet-stream</code> (some object stores do this) used to decode. After #1478
      it fails with <code>unsupported_content_type</code>. Serve it with a text type or a
      <code>charset</code>.
    </blockquote>

    <h2>Fetch a source as bytes</h2>

    <p>
      <em>Lands with #1478.</em> An I/O layer can offer an optional
      <code>fetch_bytes(request)</code> method. It returns a <code>FetchedBytes</code> with two
      fields: <code>body</code>, the bytes exactly as received, and <code>media_type</code>, the
      bare, lower-cased type (parameters dropped), or <code>None</code>.
    </p>

    <ul>
      <li>
        <code>HttpIOLayer.fetch_bytes</code> returns the response body unmodified. Errors, retries,
        idempotency keys and redirects behave as they do on the text path.
      </li>
      <li>
        <code>StaticIOLayer</code> now takes <code>str</code> or <code>bytes</code> values in
        <code>fetch_map</code>, and serves bytes from <code>fetch_bytes</code> as they are.
        <code>media_types</code> sets the type it reports.
      </li>
      <li>
        <code>url4.io.media.fetch_bytes(io, request)</code> works with any adapter. If the adapter
        has no <code>fetch_bytes</code>, it returns the adapter's text encoded as UTF-8.
      </li>
      <li>
        A source's <code>;accept=</code> annotation is sent as the <code>Accept</code> header on
        <code>fetch_ex</code> and <code>fetch_bytes</code>, word for word. Shorthands such as
        <code>accept=csv</code> are not expanded. With no annotation, the HTTP client's default
        (<code>*/*</code>) applies.
      </li>
    </ul>

    <CodeBlock :code="bytesFetch" language="python" />

    <h2>Name a file by its hash</h2>

    <p>
      <em>Lands with #1482.</em> A file ref names a file by its sha256, and the node that evaluates
      that level of the expression resolves it.
    </p>

    <CodeBlock :code="refForms" language="bash" />

    <ul>
      <li>
        <code>/blob/sha256/&lt;hex&gt;</code> is a relative path, fetched from the evaluating node
        with <code>fetch_bytes</code>.
      </li>
      <li>
        <code>blob:sha256/&lt;hex&gt;</code>, unquoted, is a new syntax node, <code>BlobRef</code>.
        It is read from the evaluating node's own store, at the same
        <code>/blob/sha256/&lt;hex&gt;</code> path.
      </li>
      <li>Quoted, <code>'blob:…'</code> is plain text and is never resolved.</li>
      <li>
        <em>On main:</em> <code>(blob:sha256/…)!…</code> without <code>src=</code> is a
        <code>ParseError</code> ("bare-token data binding requires 'src='").
      </li>
      <li>Any other relative path or URL resolves exactly as before.</li>
    </ul>

    <p>
      The bytes are hashed after every fetch. If they do not match the digest in the ref, the source
      fails with <code>x.blob_digest_mismatch</code>. A resolved ref stays text: everything
      downstream (joins, <code>$name</code> substitution, a model route) sees the ref as written.
      The bytes and the media type travel with that text for a consumer that can attach them.
    </p>

    <p>
      Nothing in #1478 or #1482 hands the bytes to a model yet. A model route still receives the ref
      text. Attaching the file to the model call is separate, follow-up work.
    </p>

    <CodeBlock :code="refRun" language="python" />

    <p>
      A file ref in collection position (the left side of <code>*</code>) iterates like the same
      body fetched as text, if it decodes as UTF-8 and its type is text or a declared collection
      type. A binary file there fails with <code>unsupported_content_type</code>. A nested
      expression addressed to another node is forwarded unchanged, and that node resolves its own
      refs from its own store.
    </p>

    <h2>Remote blobs are not supported in v1</h2>

    <p>
      A ref to another node, <code>url4://&lt;node&gt;/blob/sha256/&lt;hex&gt;</code>, parses but
      does not resolve in v1. Fetching a file from another node crosses a network boundary, and that
      needs its own policy first.
    </p>

    <p>
      <em>Lands with #1482:</em> the ref fails with <code>x.blob_peer_not_allowed</code> before any
      network I/O. The I/O adapters have an interim allowlist (<code>blob_peers</code>). It is empty
      by default, and <code>Url4Node</code>, the <code>url4</code> CLI and the engine do not set it.
      Even an allowlisted fetch never follows a redirect. The file-input spec names this refusal
      <code>remote_blob_unsupported</code>. That code is not implemented yet.
    </p>

    <h2>Not available yet</h2>

    <ul>
      <li>
        <strong>Inline <code>data:</code> URIs.</strong> <em>On main</em>, a <code>data:</code> URI
        is never resolved inside an expression. Unquoted,
        <code>(img:src=data:image/png;base64,…)</code> is a <code>ParseError</code>. Quoted, it is
        plain text. Inline files attached to a benchmark Case are planned and not in #1478 or #1482.
      </li>
      <li>
        <strong>Per-file size caps.</strong> Neither PR limits the size of a fetched file or a blob.
        <em>On main</em>, the engine caps a whole run spec at 1 MiB (<code>spec_too_large</code>)
        and a direct request's path and query at 8 KiB (414 <code>uri_too_long</code>). Neither is
        specific to files.
      </li>
      <li>
        <strong>A blob store.</strong> A node serves <code>/blob/sha256/&lt;hex&gt;</code> only if
        its I/O layer or a data route serves that path. url4 does not ship a store.
      </li>
    </ul>

    <h2>Errors</h2>

    <table>
      <thead>
        <tr>
          <th>Code</th>
          <th>When</th>
          <th>Lands with</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>unsupported_content_type</code></td>
          <td>
            A binary body on a text path, or a binary file ref in collection position. Permanent.
          </td>
          <td>#1478 (text path), #1482 (collection)</td>
        </tr>
        <tr>
          <td><code>source_not_found</code></td>
          <td>
            The node has no bytes for the ref: the store path answers 404 or 410, or the ref uses
            another algorithm or a malformed digest (refused with no I/O). Permanent; a node answers
            it as HTTP 404.
          </td>
          <td>#1482</td>
        </tr>
        <tr>
          <td><code>x.blob_digest_mismatch</code></td>
          <td>The bytes served do not hash to the ref's sha256. Permanent.</td>
          <td>#1482</td>
        </tr>
        <tr>
          <td><code>x.blob_peer_not_allowed</code></td>
          <td>A <code>url4://&lt;node&gt;/blob/…</code> ref (see above). Permanent, no I/O.</td>
          <td>#1482</td>
        </tr>
        <tr>
          <td><code>ParseError</code></td>
          <td>
            A bare <code>blob:…</code> token without <code>src=</code>, or an unquoted
            <code>data:</code> URI.
          </td>
          <td>on main</td>
        </tr>
      </tbody>
    </table>

    <h2>Where the code lives</h2>

    <ul>
      <li>
        <code>packages/url4/src/url4/io/media.py</code>: the bytes port and the text rule (#1478).
      </li>
      <li>
        <code>packages/url4/src/url4/core/blob_ref.py</code> and
        <code>src/url4/dag/nodes/blob.py</code>: the ref forms and their resolution (#1482).
      </li>
      <li>
        <a :href="`${GH_BLOB}/packages/url4/src/url4/core/errors.py`" target="_blank" rel="noopener"
          ><code>src/url4/core/errors.py</code></a
        >: the error codes.
      </li>
    </ul>
  </DocLayout>
</template>
