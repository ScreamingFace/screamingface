<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_BLOB = 'https://github.com/ScreamingFace/screamingface/blob/main'
const GH_PR = 'https://github.com/ScreamingFace/screamingface/pull'

const fileUrl = `(img:src=https://example.com/chart.png)!'Describe the chart'`

const guardConfig = `from url4.io.http import HttpIOLayer, SourceGuard

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
)`

const refForms = `(img:src=/blob/sha256/<hex>)!'Describe'              # local path on the evaluating node
(img:src=blob:sha256/<hex>)!'Describe'               # local bare token, same store
(img:'blob:sha256/<hex>')!'Describe'                 # quoted: plain text, never resolved
(blob:sha256/<hex>)!'Describe'                       # ParseError: a bare token needs src=
(img:src=url4://n2.example/blob/sha256/<hex>)!'d'    # remote blob: refused in v1`

const modelsRow = `GET /v1/models

{"id": "<provider>/<model>", ..., "input_modalities": ["text", "image", "pdf"]}
{"id": "<provider>/<model>", ..., "input_modalities": ["text"]}`
</script>

<template>
  <DocLayout
    title="Files in url4"
    description="Images and PDFs as url4 sources: file URLs, sha256 blob refs, what v1 refuses, and the limits."
    :navigation="navigation"
  >
    <blockquote>
      <strong>Partly unreleased.</strong> The contract is the file-input spec in
      <a :href="`${GH_PR}/1450`" target="_blank" rel="noopener">#1450</a>, still in review. Each
      section says where its behaviour stands: <em>on main</em> (merged, not yet in a published
      <code>url4</code> release; the last one is 1.5.1), <em>lands with #N</em> (an open pull
      request), or <em>specified</em> (in the spec, no code yet).
    </blockquote>

    <p>
      A <RouterLink to="/learn/url4">url4</RouterLink> source has always resolved to text. v1 of
      file input lets a source be an image or a PDF that reaches the model as a file, not as garbled
      text. The expression stays a string: files travel beside it, never inside it.
    </p>

    <p>A file enters a run in one of two ways:</p>
    <ul>
      <li>
        <strong>A url4 source:</strong> an <code>https://</code> file URL, or a
        <code>sha256</code> blob ref. Both are resolved by the node that evaluates the expression.
      </li>
      <li>
        <strong>A benchmark Case:</strong> pictures and PDFs written inline in the Case itself. This
        path does not go through url4 (see <a href="#cases">Benchmark Cases</a>).
      </li>
    </ul>

    <h2>A file URL as a source</h2>

    <CodeBlock :code="fileUrl" language="bash" />

    <p>
      The source is fetched lazily, when the run needs it, exactly like any other URL source. What
      changes is what the engine does with the body:
    </p>
    <ul>
      <li><strong>Text body:</strong> unchanged. It is a text source, as it always was.</li>
      <li>
        <strong>Non-text body</strong> (an image, a PDF): <em>specified.</em> The bytes are hashed,
        stored for the run, and sent to the model as a file part at that source's position. On main
        today the body is still decoded as text.
        <em>Lands with <a :href="`${GH_PR}/1478`" target="_blank" rel="noopener">#1478</a>:</em> the
        text path refuses a binary body with <code>unsupported_content_type</code> instead of
        decoding it, a step toward the attachment.
      </li>
    </ul>

    <h3>The transport guard</h3>

    <p>
      <em>On main (<a :href="`${GH_PR}/1521`" target="_blank" rel="noopener">#1521</a>).</em> Every
      source fetch through url4's <code>HttpIOLayer</code> passes one destination guard, text and
      file sources alike:
    </p>
    <ul>
      <li><code>https</code> only. <code>http</code> is a configuration switch, off by default.</li>
      <li>
        DNS is resolved first. Loopback, private, link-local (including the cloud metadata address
        <code>169.254.169.254</code>), CGNAT, unspecified, multicast and reserved addresses are
        refused, as are IPv6 forms that embed them. The connection goes to the vetted IP, so a
        second DNS answer cannot redirect it.
      </li>
      <li>
        At most 3 redirects. Every hop is checked by the same rules, and a hop from
        <code>https</code> to <code>http</code> is refused.
      </li>
      <li>
        A streaming cap on decoded bytes (20 MiB by default) that aborts mid-stream, a connect
        timeout and one total deadline for the whole fetch.
      </li>
      <li>Proxy environment variables are ignored.</li>
    </ul>

    <CodeBlock :code="guardConfig" language="python" />

    <p>
      An <code>HttpIOLayer</code> built on a client you inject keeps only the size cap: you chose
      that client's destinations and timeouts.
    </p>

    <h2>Blob refs</h2>

    <p>
      A blob ref names a file by the sha256 of its bytes. v1 has two local forms, both read from the
      evaluating node's own store:
    </p>

    <CodeBlock :code="refForms" language="bash" />

    <ul>
      <li>
        <code>/blob/sha256/&lt;hex&gt;</code> is a relative path.
        <code>blob:sha256/&lt;hex&gt;</code> is a bare token and needs <code>src=</code>.
      </li>
      <li>
        The bytes are checked against the digest on every read. A mismatch is
        <code>x.blob_digest_mismatch</code>, permanent.
      </li>
      <li>
        A digest the node does not hold is <code>source_not_found</code>. Under the spec, so is a
        digest stored for another run or tenant: a digest is not a bearer capability.
      </li>
    </ul>

    <p>
      <em>Lands with <a :href="`${GH_PR}/1482`" target="_blank" rel="noopener">#1482</a>:</em> the
      <code>blob:</code> token, resolution at the evaluating node, the digest check and the
      remote-blob refusal. <em>On main:</em> the <code>ParseError</code> for a bare token without
      <code>src=</code>. <em>Specified:</em> the run-scoped store and handing the verified bytes to
      the model. Until those land, a resolved ref reaches a model route as its text.
    </p>

    <p>
      <strong>Uploading a blob is coming.</strong> There is no Python client API for putting a file
      into a node's blob store yet.
    </p>

    <h2>Not in v1</h2>

    <ul>
      <li>
        <strong>Remote blobs.</strong> Every <code>url4://&lt;node&gt;/blob/…</code> ref fails with
        <code>x.remote_blob_unsupported</code>, permanent, before any network I/O, whatever the
        authority (the evaluating node's own name included). <em>Lands with #1482.</em>
      </li>
      <li>
        <strong>Remote-node calls.</strong> A nested expression addressed to another node,
        <code>(url4://n2.example/v1(…)!'…')!'…'</code>, is refused until node-to-node authentication
        is specified. <em>Specified:</em> the code is <code>x.remote_node_unsupported</code>, before
        any I/O. <em>On main today:</em> the guard refuses it as
        <code>x.source_destination_blocked</code>, because its peer allowlist is empty by default.
      </li>
      <li>
        <strong><code>data:</code> URIs in an expression.</strong> Unquoted, the <code>;</code> and
        <code>,</code> split it and it is a <code>ParseError</code>; quoted, it is plain text.
        Inline <code>data:</code> belongs in Case envelopes only.
      </li>
    </ul>

    <h2 id="cases">Benchmark Cases</h2>

    <p>
      <em>On main (<a :href="`${GH_PR}/1507`" target="_blank" rel="noopener">#1507</a>).</em> A Case
      with pictures or PDFs uses the candidate-input envelope
      <code>screamingface.candidate-input.v2</code>. Its parts are OpenAI content parts:
      <code>image_url</code> (PNG, JPEG, GIF or WebP) and <code>file</code> (PDF only), each as a
      <code>data:</code> URI, in user messages only. A text-only Case stays v1. Benchmark files are
      built into the benchmark image, so a Case never fetches anything at run time.
    </p>

    <h2>Limits</h2>

    <table>
      <thead>
        <tr>
          <th>Limit</th>
          <th>Value</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Gateway request body</td>
          <td>
            8 MiB (8,388,608 bytes), <code>AIGW_MAX_REQUEST_BYTES</code>. Over it: 413
            <code>request_too_large</code>, before any upstream spend.
          </td>
          <td>on main (#1479)</td>
        </tr>
        <tr>
          <td>Pictures per Case</td>
          <td>at most 20, refused at import by name</td>
          <td>lands with #1554</td>
        </tr>
        <tr>
          <td>Case size with pictures inline</td>
          <td>at most 8,000,000 bytes, leaving room under the gateway cap</td>
          <td>lands with #1554</td>
        </tr>
        <tr>
          <td>One fetched source</td>
          <td>20 MiB decoded, by default (<code>SourceGuard.max_bytes</code>)</td>
          <td>on main (#1521)</td>
        </tr>
      </tbody>
    </table>

    <p>There is no per-picture limit.</p>

    <h2>Which models take files</h2>

    <p>
      <em>On main (<a :href="`${GH_PR}/1451`" target="_blank" rel="noopener">#1451</a>).</em> Each
      row of the gateway's <code>/v1/models</code> carries <code>input_modalities</code>, a subset
      of <code>text</code>, <code>image</code> and <code>pdf</code>, always starting with
      <code>text</code>. When the gateway has no evidence for a model, the row says
      <code>["text"]</code>: unknown never means vision.
    </p>

    <CodeBlock :code="modelsRow" language="bash" />

    <p>A part a model cannot take is refused loudly, never dropped:</p>
    <ul>
      <li>
        <em>On main.</em> The gateway takes an image or a PDF as a <code>data:</code> URI and never
        fetches a URL itself. The one exception is Codex, which forwards an <code>https</code> image
        URL for OpenAI to fetch. Where a provider adapter cannot carry a part (a PDF to Ollama,
        media in an Anthropic system prompt), it answers 422 <code>unsupported_content_part</code>
        before dispatch. Not retryable.
      </li>
      <li>
        <em>Specified.</em> The engine checks <code>input_modalities</code> at admission and refuses
        a blind model by name with <code>intent_error</code>, before any spend.
      </li>
    </ul>

    <h2>Errors</h2>

    <table>
      <thead>
        <tr>
          <th>Code</th>
          <th>When</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>x.source_destination_blocked</code></td>
          <td>
            Disallowed scheme, a refused address on any hop, an <code>https</code> to
            <code>http</code> redirect, or a <code>url4://</code> peer off the allowlist. Permanent.
          </td>
          <td>on main</td>
        </tr>
        <tr>
          <td><code>x.source_redirect_limit</code></td>
          <td>More redirects than the limit (default 3). Permanent.</td>
          <td>on main</td>
        </tr>
        <tr>
          <td><code>x.source_too_large</code></td>
          <td>The decoded body passed the cap. Permanent.</td>
          <td>on main</td>
        </tr>
        <tr>
          <td><code>x.source_timeout</code></td>
          <td>Connect timeout, or the total deadline across all hops. Retryable.</td>
          <td>on main</td>
        </tr>
        <tr>
          <td><code>unsupported_content_type</code></td>
          <td>A binary body on a text path. Permanent.</td>
          <td>lands with #1478</td>
        </tr>
        <tr>
          <td><code>source_not_found</code></td>
          <td>The node does not hold the blob. Permanent.</td>
          <td>lands with #1482</td>
        </tr>
        <tr>
          <td><code>x.blob_digest_mismatch</code></td>
          <td>The bytes do not hash to the ref's sha256. Permanent.</td>
          <td>lands with #1482</td>
        </tr>
        <tr>
          <td><code>x.remote_blob_unsupported</code></td>
          <td>Any <code>url4://…/blob/…</code> ref. Permanent, no I/O.</td>
          <td>lands with #1482</td>
        </tr>
        <tr>
          <td><code>x.remote_node_unsupported</code></td>
          <td>Any <code>url4://</code> remote-node call. Permanent, no I/O.</td>
          <td>specified</td>
        </tr>
        <tr>
          <td><code>request_too_large</code></td>
          <td>Gateway body over 8 MiB. HTTP 413.</td>
          <td>on main</td>
        </tr>
        <tr>
          <td><code>unsupported_content_part</code></td>
          <td>The provider adapter cannot carry the part. HTTP 422.</td>
          <td>on main</td>
        </tr>
      </tbody>
    </table>

    <p>
      Codes with the <code>x.</code> prefix are implementation codes; they stay prefixed until the
      url4 spec adopts them.
    </p>

    <h2>Where the code lives</h2>

    <ul>
      <li>
        <a
          :href="`${GH_BLOB}/packages/url4/src/url4/io/_source_policy.py`"
          target="_blank"
          rel="noopener"
          ><code>packages/url4/src/url4/io/_source_policy.py</code></a
        >: the guard's rules and <code>SourceGuard</code>.
      </li>
      <li>
        <a :href="`${GH_BLOB}/packages/url4/src/url4/core/errors.py`" target="_blank" rel="noopener"
          ><code>packages/url4/src/url4/core/errors.py</code></a
        >: the url4 error codes.
      </li>
      <li>
        <a
          :href="`${GH_BLOB}/apps/aigateway/src/aigateway/core/input_modalities.py`"
          target="_blank"
          rel="noopener"
          ><code>apps/aigateway/src/aigateway/core/input_modalities.py</code></a
        >
        and
        <a
          :href="`${GH_BLOB}/apps/aigateway/src/aigateway/core/content_parts.py`"
          target="_blank"
          rel="noopener"
          ><code>content_parts.py</code></a
        >: modalities and the part gate.
      </li>
    </ul>
  </DocLayout>
</template>
