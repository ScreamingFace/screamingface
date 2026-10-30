# Spec — file input across url4, engine and gateway (`OME-1535`)

Epic `OME-1529`. Status: **draft for review** (url4: Kevin; gateway: Dmitry; architecture: HupBaHa).
The proposed `x.*` url4 wire codes of this revision **await Kevin's url4 wire approval** (§4).
Owner decisions F1–F4 locked by Sergey on 2026-10-21 (§2); his follow-up decisions D1–D6 of the
same day are folded into F1 and F2, his review-round-4 decision (C6 disabled in v1) into F1b, and
his review-round-5 decisions (owner, 2026-10-26: https sources pre-materialized and `attachments[]`
frozen; no engine-key change in v1; per-run attachment caps and the narrowed Case-ingress
guarantee) into F1b, F2, F3, §2.7 and §4, and his review-round-6 decisions (owner, 2026-10-27:
v1 Case execution pictures-only) into §2.7 and §3, and his review-round-7 decisions (owner,
2026-10-27: explicit attachment opt-in through `;accept=`, text sources unchanged, reachability-aware
manifest, identity including guard policy; superseding round 6's all-sources manifest) into F1b, F2,
§3 and §4, and his review-round-8 decisions (owner, 2026-10-27: exactly one attachment type per
`;accept=`, no wildcard or list) into F1b, §3 and §4, and his review-round-9 correction (owner,
2026-10-27: attachment URLs are literal only, because the grammar cannot express a row-derived one)
into F1b and §4, and his review-round-10 decision (owner, 2026-10-27: an attachment's whole
reachability dependency must be model-free) into F1b, §3 and §4.

**Snapshot.** Every "today" claim is pinned to `main` at [`ec4b632b2`][snap] (2026-10-21, after
#1447), and so is every `file:line` citation unless its link names another commit: the F3
gateway-cache link is pinned to `3f2b3a6ef`, the engine-key link to `f70cde71b`, the F1b classification links to `dd4bd9a47` and #1478's head `9d32862f9`. Citations are commit-qualified links,
so they stay valid when the files move. Short prefixes: `U/` = `packages/url4/src/url4/`,
`E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`I/` = `apps/screamingface-engine/src/screamingface_engine_inspect/`,
`P/` = `packages/screamingface/src/screamingface/`, `G/` = `apps/aigateway/src/aigateway/`.

**Evidence classes.** *Code* claims are reproducible at the snapshot. *Live* claims (provider
behaviour, token counts) are **dated observations** from manual runs on 2026-10-16/17 with no
durable fixture in this PR; they inform design and are not guarantees.

![File input path, today vs target](../diagrams/file-input-path.svg)

## 1. Findings per layer (today, at `ec4b632b2`)

### url4 — strings end to end

| Choke point | Evidence |
|---|---|
| The only content leaf is a string | [`U/core/nodes.py:63-66`][u-text] (`Text.value: str`) |
| Payloads are strings | [`U/dag/node.py:23`][u-node23] ("Payloads are strings"), [`:70`][u-node70] (`Payload = str \| list[str] \| SourceFailure`), [`:79`][u-node79] (`ProcessFn` returns `str`) |
| Fetch returns text | [`U/io/layer.py:81-85`][u-fetch] (`FetchResult.body: str`, `media_type` kept); [`U/io/http.py:74,80`][u-http] (`response.text`, so binary is decoded as text) |
| HTTP sources follow redirects | [`U/io/http.py:66-69`][u-redirect] (`follow_redirects=True`): one reason remote blobs are deferred (F1) |
| Peer replies are text | [`U/peer/_http.py:109`][u-peer] (`text/plain; charset=utf-8`) |
| Collections take a closed set of text types | [`U/dag/semantics/collection.py:140-142`][u-coll] |
| `;accept=` is carried but no adapter honours it | [`U/io/layer.py:69-77`][u-accept] |

Parser behaviour, reproduced with `url4.core.grammar.parse`:

- `(img:src=data:image/png;base64,AAAA)!'d'` → `ParseError` ("invalid execution-annotation key 'base64'").
- `('data:image/png;base64,AAAA')!'d'` → `Text` (a literal; never resolved).
- `(img:src=blob:sha256/ab)!'d'` → `Binding(value=Text('blob:sha256/ab'))`. It parses, but nothing resolves it yet (`OME-1539`).
- `(blob:sha256/ab)!'d'` → `ParseError` ("bare-token data binding requires 'src='"). Matches C7.

Reusable: `FetchResult.media_type`, the `;accept=` annotation, and the claim-ticket pattern of
[`ResultArtifact`][u-artifact] (`id` + `size_bytes` + `sha256`, verified before trust). `ResultArtifact`
carries **no media type**; the media type lives on the enclosing [`ResultData.media_type`][u-resultdata].

### Engine — text only, non-text content refused

| Choke point | Evidence |
|---|---|
| Sync surface: 8 KiB target cap | [`E/rest/mounts.py:277`][e-414] (414 `uri_too_long`), [`E/job_env.py:208`][e-8k] (`MAX_DIRECT_TARGET_BYTES = 8 * 1024`) |
| Run spec: 1 MiB cap | [`E/child_protocol.py:26`][e-spec26], [`:103-104`][e-spec103] (`MAX_SPEC_BYTES`, `spec_too_large`) |
| Case input becomes a string | [`E/benchmarks/case_request.py:13-31`][e-case] (dict → `json.dumps`) |
| Chat envelope refuses non-text content | [`E/world/connector.py:1535`][e-text] (`invalid_candidate_input`, "content must be text") |
| Messages are built from strings | [`E/world/connector.py:1478`][e-msgs] (`_messages(context: str \| None, intent: str \| None)`) |
| Fusion gets the Case re-serialised as text | [`P/_evaluation/candidate.py:358`][p-fusion] (`struct({"input": …, "outputs": …})`), [`:769-787`][p-fctx] |
| Request identity hashes a string context | [`E/request_identity.py:13-33`][e-key] (`path`, `params`, `context`, `intent`) |
| Judge sees text only | [`I/judge_provider.py:432`][i-judge] (`{"role": role, "content": message.text}`) |
| Inspect capture refuses images and audio | [`I/capture.py:513`][i-cap513], [`:529`][i-cap529] ("non-text content") |
| Benchmark assets are built into the image; Runner Jobs have no egress | [`I/prepare.py:8`][i-prep8] ("Run at IMAGE BUILD time"); [`E/benchmarks/nltk_data.py:38`][e-nltk] ("read-only rootfs and no network egress"). These are code comments that state the deployment intent, not an enforcement point. |
| Non-text `sample.input` refused | [`I/prepare.py:2097-2101`][i-prepin] (`PrepareError`) |

### Gateway — native media for the custom adapters (`OME-1541` #1431, `OME-1641` #1447)

- [`G/core/content_parts.py`][g-parts] parses OpenAI `content` into text, inline media (`MediaPart`) and
  `RemoteImagePart`. Anything a provider cannot carry is refused before dispatch with a typed
  **422 `unsupported_content_part`** ([`:66-83`][g-422], "not retryable"), raised by `check_messages` in the
  `prepare_chat_body` of four plugins: [gemini][g-gem], [antigravity][g-ag], [codex][g-codex], [ollama][g-oll].
- Accepted: `image_url` must be `image/*` ([`:181-197`][g-img]), with `detail` limited to `auto|low|high`
  ([`:27-29`][g-detail], [`:200-209`][g-detail2]); `file` must be `application/pdf` ([`:32`][g-pdf], [`:211-232`][g-file]). Untyped non-text parts are refused.
- Gemini and Antigravity: `inlineData`; remote image URLs are refused with `reason: remote_url` (the gateway never fetches).
- Codex: `input_text` / `input_image` / `input_file`; https image URLs are passed through, since OpenAI fetches them.
- **Ollama, at this snapshot:** the plugin runs the same gate with `allow_files=False`,
  `allow_remote_images=False` ([`G/plugins/ollama_provider/plugin.py:90-99`][g-oll]): a PDF or a remote image URL
  gets 422 `unsupported_content_part`; data-URI images are unchanged. *History:* before #1447 (e.g. at
  `637594595`) LiteLLM's `ollama_chat` conversion **silently dropped** `file` parts (observed 2026-10-16:
  PDF answered 200 with +7 prompt tokens and an unrelated answer). **v1 rule for a PDF sent to a model that cannot
  take files** (owner decision 2026-10-28, `OME-1760`): a **typed refusal at gateway dispatch**. The gateway
  answers 422 `unsupported_content_part`, and the engine connector reports it as url4 `intent_error` with
  permanence kept (§4), never a silent drop. This is a provider-level refusal at dispatch, not a model-name
  admission check (C9 covers images only), and the gateway's message names the provider, not the model.
  Implementation is pending in #1588 (`OME-1545`). There is no PDF-to-text fallback in v1; `OME-1550` was
  narrowed to office formats.
- Anthropic, OpenRouter and OpenAI (API key) do not call `check_messages`; their parts go through LiteLLM as sent.
- Still open:
  - **No request body cap** anywhere in the gateway (the only size checks under `G/` are on responses or object-store uploads). → `OME-1542`
  - **Anthropic OAuth drops non-text system parts:** [`G/plugins/anthropic_provider/chat_handler.py:180-197`][g-anth] keeps only `type == "text"`. → `OME-1542`
  - **`/v1/models` carries no input-modality field.** Only HuggingFace discovery parses `input_modalities` ([`:74`][g-hf74], [`:129`][g-hf129]), and nothing exposes it. → `OME-1537`
  - **SSRF:** LiteLLM may fetch caller `http(s)` image URLs for the pass-through providers (Anthropic, OpenRouter). **UNVERIFIED**; from the 2026-10-07 research. → `OME-1542`

## 2. Normative decisions (owner, locked 2026-10-21)

### F1 — Remote blobs are deferred from v1

**Decision.** v1 supports exactly two blob sources: **local, run-scoped blobs** and **inline `data:` at
Case ingress**. **Every** `url4://<authority>/blob/...` ref is remote in v1, whatever its authority:
there is no self-recognition, so a ref naming the evaluating node itself is remote too. It fails with
the typed, permanent **`x.remote_blob_unsupported`** at resolution, **before any network I/O** (no DNS
lookup, no connection). Only an authority-less ref is local: the bare path `/blob/sha256/<hex>` (C1) and
the bare token `blob:sha256/<hex>` (C3). Both are a **direct tenant + run store read** on the evaluating
node; neither is rewritten into an authority-bearing `url4://` URL, so a local ref can never re-enter
source classification as a remote one. There is no
"fetch once and pin" for remote sources in v1.

**Rationale.** A remote fetch is an SSRF/egress boundary. url4 HTTP sources follow redirects to
arbitrary translated targets ([`U/io/http.py:66-69`][u-redirect]), and "no egress" for Runner Jobs is a
code comment, not an enforced policy. Shipping remote blobs without a normative policy would open that
boundary by default; refusing them keeps v1 closed while the local path proves the content-part model.

**Bar for the follow-up remote-blob spec** (its own ticket; must be normative before implementation):
allowed schemes and authority allow-list; authentication of the fetching node to the remote node; DNS
resolution with refusal of private, loopback, link-local and cloud-metadata addresses, re-checked on
every redirect hop; a redirect-count limit; connect and total deadlines; a streaming byte limit (abort
on overflow, not after download); media-type validation against the declared type and sniffed bytes;
per-run file count and aggregate byte limits; and the typed failures for each (blocked destination,
auth failure, timeout, too large). Alternatively it may delegate ingestion to a constrained fetch
service that owns this policy.

### F1b — `https://` file sources stay in v1, behind one destination guard (`OME-1544`)

**Decision** (owner, 2026-10-21, after F1). F1 defers **`url4://` remote blobs**, meaning node-to-node
blob transfer. It does **not** remove plain `https://` sources such as `(img:src=https://…/a.png)`. In v1
these are fetched by the evaluating node through **one destination guard in the url4 HTTP transport**.
Every source fetch passes through that guard: today's text path and #1478's `fetch_bytes` alike. The
guard also fixes bug `OME-1704`, where text sources fetch any URL on main today.

**Guard rules (normative):**
- **Schemes:** `https` only by default; `http` is a configuration switch, off by default.
- **Address check:** DNS is resolved first. Loopback, private (RFC 1918, `fc00::/7`), link-local
  (`169.254/16` including metadata `169.254.169.254`, `fe80::/10`), CGNAT `100.64/10`, unspecified,
  multicast and reserved ranges are refused, as are IPv4-mapped IPv6 forms of any of these.
- **Pinning:** the connection goes to the vetted IP, keeping SNI and `Host`, so a second DNS answer
  cannot redirect it (no rebinding).
- **Redirects:** every hop is re-checked against the same rules. At most 3 hops (configurable). A hop
  from `https` to `http` is refused.
- **Time:** a connect timeout plus one **total** deadline for the whole fetch, redirects included.
- **Size:** a streaming byte cap that aborts mid-stream. The cap counts decoded bytes.
- **Escape hatch:** loopback may be allowed only through explicit configuration for tests and dev; off
  by default.
- **Errors and logs:** each refusal raises a typed `x.` error (see §4). Response bodies are never logged.
- **Remote-node calls are disabled in v1** (owner, review round 4). Destination allowlisting does not
  authenticate the caller at the remote node, so every `url4://` remote-node call, for example a nested
  remote expression (C6), is refused by the url4 node resolver with the typed, permanent
  **`x.remote_node_unsupported`** before any I/O (no DNS lookup, no connection), until a node-to-node
  authentication spec defines outbound identity, credential transport and rotation, inbound
  authorization, replay behaviour, typed auth failures and tests at both nodes. The guard's
  operator-configured **peer allowlist** (#1521) stays **empty by default and must not be populated**
  until that spec exists. Blob transfer between nodes stays deferred under F1.
  The refusal applies in a **node context** (owner, 2026-10-26, #1482): every evaluation a `Url4Node`
  runs, the engine's included, and, inside a `Client(node=…)` evaluation, everything except the
  client's own outer hop to its node. A bare library `url4.run()` is not a node context and is
  unchanged. Plain `url4://host/path` data fetches are not remote-node calls; the transport guard
  governs them (`x.source_destination_blocked` while the peer allowlist is empty).
- **Scope of attachments: explicit opt-in, pre-materialize, then freeze** (owner, 2026-10-26, review
  round 5; opt-in, reachability, identity and classification: owner, 2026-10-27, review round 7, which
  supersedes the round-6 all-sources manifest and "required wins"; one exact type: owner,
  2026-10-27, review round 8; literal URLs only: owner, 2026-10-27, review round 9).
  - **Attachment sources (opt-in, no grammar change)** (owner, 2026-10-27, review round 8). An
    `https://` source is an **attachment source** iff its existing `;accept=` annotation is **exactly
    one** lower-case type from the **attachment types** `image/png`, `image/jpeg`, `image/gif`,
    `image/webp`, `application/pdf`. There are no wildcards and no lists: a url4 execution value
    admits neither `*` nor a comma, so neither could be written without a grammar change. Any other
    `;accept=` value, or none, makes it a **text source**.
  - **Text sources keep today's url4 semantics exactly.** They are not pre-materialized, not
    deduplicated and never attached: each occurrence is fetched lazily through its own `GuardNode`
    with its own `;optional`, `;t=` and `;retry=`, and is classified by #1478's existing text rule
    ([`is_text_media_type`][pr1478-text]: a missing type, `text/*`, the JSON/XML/YAML/JS family,
    `+json`/`+xml`/`+yaml`, and a non-binary `application/*` with `charset` are text) and decoded
    through the response text, so the declared charset is honoured. **An expression with no
    attachment source is byte-identical to today**, which is what keeps F2's text-only guarantee.
  - **Reachability-aware manifest (normative).** Before the first model call a run-admission and
    materialization phase builds the **attachment manifest**. Non-model collection inputs are resolved
    first, with their normal source semantics, and execution reuses those results. An iteration body
    over zero rows contributes nothing and causes no I/O. Only attachment sources reachable in the
    actual rows (and in lazy groups and nested fragments as authored) enter the manifest, in preorder
    of the expanded expression, and all of them are materialized before the first model call.
  - **Literal attachment targets** (owner, 2026-10-27, review round 9, narrowing round 8). An
    attachment source's URL and its `;accept=` must **both be literal** in the authored expression.
    Anything else (a row-substituted, model-derived or fetched-body-derived URL) is refused with the
    permanent **`x.source_not_static`** (§4) before any fetch or model call. Round 8 allowed URLs
    substituted from collection rows, but url4's grammar cannot express that: `https://h/$item` is
    fetched literally, and `src=$item;accept=…` is a variable source that yields the row text and
    ignores `;accept=`. Row-derived attachment URLs are deferred to `OME-1748` (improvement idea). The
    code applies to attachment sources only; a text source may be dynamic, as today.
  - **Model-free reachability** (owner, 2026-10-27, review round 10; confirms the `OME-1543`
    reading). An attachment source is also refused with `x.source_not_static`, before any fetch or
    model call, when the collection of **any enclosing iteration** depends on model execution, because
    its cardinality and therefore the source's reachability are known only after a model call: a
    processed group, a model call, a remote expression, a nested model-dependent iteration, or a
    binding to one of these. The whole reachability dependency of an attachment source must be
    model-free, so the manifest is always complete before the first model call. For example,
    `((https://rows)!'Produce JSON rows')*(https://files/static.png;accept=image/png)!'Use $item'` is
    refused.
  - **Identity, one flight, one attachment per identity.** The materialization identity is
    `(URL, accept, effective guard policy: ;optional, ;t=, ;retry=)`. Occurrences with an identical
    identity share **one flight**, including its whole retry sequence under that policy, and yield
    **one attachment**, placed at the identity's **first occurrence in manifest preorder**, never in
    completion order. Occurrences that differ in any part of the identity are separate identities,
    each executed under its own policy and each listed as its own attachment, even when the bytes are
    equal. A terminal failure of an `;optional` identity omits it (logged with its typed code); of a
    required identity, it fails the run before any model call.
  - **One binary-safe fetch** (#1478's `fetch_bytes`, through the guard) yields the bytes and the
    media type; there is no second fetch.
  - **Classification of attachment sources (normative).** The response's bare, lowercased media type
    ([`bare_media_type`][pr1478-media]) must **equal** the requested `;accept=` type (owner, 2026-10-27,
    review round 8). The attachment types are a fail-closed subset of the gateway's gate (any image type
    for `image_url`, [`G/core/content_parts.py:242`][g-img-main]; `application/pdf` for `file`,
    [`:42`][g-pdf-main]). Otherwise, including a missing Content-Type (`bare_media_type()` returns `None`) or a value that is
    not exactly one media type, the source fails with `unsupported_content_type` (permanent, C8,
    #1478's code): optional → omitted, required → the run fails. **No byte sniffing.**
  - **Write-through.** A classified attachment is hashed into the tenant+run store (write-through,
    `OME-1540`) and appended to `attachments[]` as above. Only attachment sources write through.
  - **Freeze.** When pre-materialization ends, `attachments[]` is frozen (F2): no attachment source is
    fetched, re-fetched, added or reordered after the first model call.
  - **Per-run caps** (owned by `OME-1543`; unchanged): at most **20** entries and at most
    **8,000,000 bytes** aggregate (decoded bytes) per run, both counted over the **whole**
    `attachments[]`: every local blob ref (C1, C3) plus every https attachment. Enforced during
    pre-materialization; exceeding either is refused before any model call with the permanent
    `x.attachments_too_many` or `x.attachments_too_large` (§4).
  - **Conformance cases** (`OME-1543`): an empty collection causes no I/O and the run succeeds;
    duplicate text-source occurrences with differing `;t=`, `;retry=` or `;optional` behave exactly as
    today; text sources with no Content-Type, XML, `+json`, YAML, a charset-bearing `application/*`
    type and Latin-1 text are unchanged; an attachment source with a wrong or missing type gets
    `unsupported_content_type`, and so does a response type that differs from the requested one (a
    `;accept=image/png` source answered with `image/jpeg`); the same URL with and without a media
    `;accept=` takes the text path and the attachment path independently; parallel siblings with an
    identical identity cause one fetch and one attachment; reversed completion order still yields
    manifest-preorder attachments; a literal attachment source inside an iteration body is fetched
    once (one identity) when any row is reached and not at all for an empty collection; a substituted
    or variable attachment URL (`src=$item;accept=image/png`, or one derived from a fetched body) gets
    `x.source_not_static` before any fetch; a model-derived attachment URL gets `x.source_not_static`;
    a literal attachment source inside an iteration over a model-produced collection gets
    `x.source_not_static` before any I/O both when that collection would turn out empty and when it
    would turn out non-empty.

  Rationale for opting in through `;accept=`: the grammar does not preserve `src=`. `(src=https://a)`
  and `(https://a)` parse to the same `Url` source ([`U/core/grammar.py:186-188`][u-src]), so a `src=`
  binding cannot mark an attachment, while `;accept=` is already a per-source annotation
  ([`U/io/layer.py:69-77`][u-accept]). `OME-1544` is the guard only. (Owner, 2026-10-21; revised
  2026-10-22, `OME-1543` Q-B; lifecycle and caps 2026-10-26, review round 5; opt-in model
  2026-10-27, review round 7; one exact type 2026-10-27, review round 8; literal URLs only
  2026-10-27, review round 9.)

  **Handoff.** `OME-1540`'s description now matches F1b (only attachment sources write through) and
  F3 (steps 1–4, two authorization paths), as of 2026-10-27.

**Where it runs.** Fetches happen on the node that evaluates the expression (the engine's serve path).
Benchmark Runner Jobs keep their no-egress intent, because benchmark assets are pinned at image build
time (`OME-1271`) and never fetched at run time. Per-run attachment count and aggregate bytes are the
caps above; each single fetch is also bounded by the guard's streaming byte cap. Node-to-node authentication is the prerequisite for both
F1's deferred remote blobs and remote-node calls (C6); neither is enabled in v1.

### F2 — Attachments are a side-channel; the payload stays `str`

**Decision.** The run context carries an ordered **`attachments[]`** of blob refs:

| Field | Required | Meaning |
|---|---|---|
| `digest` | yes | `sha256:<hex>` of the bytes |
| `media_type` | yes | e.g. `image/png`, `application/pdf` |
| `filename` | no | carried to `file` parts |
| `detail` | no | `auto` \| `low` \| `high`, carried to `image_url` parts |

`Payload` stays `str` ([`U/dag/node.py:70`][u-node70]). **Nothing scans strings for blob-looking text**: a ref
becomes an attachment only from structure (a source in the parsed AST, such as a `src=` blob binding or
an `https://` attachment source opted in by its `;accept=` (F1b), or a typed part in a Case envelope), never from
the contents of a payload, a member output or a JSON value.

**Content layout.** Every model-calling node — ensemble members, model and recipe synthesizers
(fusion), reducers, and the judge — builds the OpenAI `content` of its user message as
`[attachment parts in attachments[] order…, then the text]`. When url4 `attachments[]` are merged into
a multi-message candidate envelope, their parts go on the **last user message** only; earlier messages
keep their text content unchanged (D3). D3 covers only those url4 attachments: parts already written in a
v2 Case envelope (§2.7) keep their position. Each attachment becomes `image_url` (for
`image/*`) or `file` (otherwise) with a `data:` URI built from the verified bytes. A node with no
attachments sends `content` as a plain string, exactly as today.

**Fusion.** The existing `{input, outputs}` rendering ([`P/_evaluation/candidate.py:769-787`][p-fctx])
is the trailing text part. url4 `attachments[]` precede it and are never inlined into, or referenced
from, that JSON. For a text-only Case the fusion text is unchanged and, with no attachments, is the
only part. For a Case with media parts (§2.7), the synthesizer gets every media part of the Case, in
Case order, followed by the `{input, outputs}` text. In that text, `input` shows each part as a
placeholder (type, its 1-based position among the media parts sent, media type, size, filename when
present; no digest) so the bytes are not sent a second time; the placeholder carries no resolvable
reference, so nothing scans for it. The connector finds those parts by structure: it parses the
rendered object and reads its `input` member with the §2.7 envelope reader, never by scanning text. A
reducer's signal calls read the same object, with `panel` in place of `outputs`, and are built the
same way. Member outputs are text and add no attachments.

**Text blobs in collections (D4).** A blob read in collection position whose media type is in the
collection text set ([`U/dag/semantics/collection.py:140-142`][u-coll]) is used as text and is **not**
added to `attachments[]`. Any other type there stays `unsupported_content_type` (C8).

**Propagation (v1).** Attachments are fixed at run start, without exception (owner, 2026-10-26,
review round 5): before the first model call the run resolves its local blob refs and pre-materializes
every reachable `https://` attachment source (F1b; text sources stay lazy and are never
attached); Case parts travel in the v2 envelope instead (§2.7). The list is then
**frozen** as one immutable snapshot that every node sees unchanged: pipelines, siblings under parallel
fan-out, nested local sub-expressions, reducers and retries. A node cannot add, drop or reorder
attachments in v1, and a retry never re-fetches. Because the list is fixed before execution, a local
blob source marked `;optional` that fails to resolve **fails the whole run** with its own code (§4); it
is never dropped from the list (D5). A failed `;optional` `https://` attachment source is instead
omitted before the snapshot is taken (F1b), so the snapshot is still fixed before any model call.
A nested expression addressed to a **remote** node (C6) is refused in v1 (`x.remote_node_unsupported`,
F1b). When node-to-node authentication enables it, the remote node resolves its own sources against
its own store, and the outer run's attachments are not shipped to it, because that would be a remote
blob transfer (F1).

**Judge.** The judge uses the same builder. Which attachments a grading call receives is the
benchmark's grading policy: under `OME-1271` v1 the grader receives none, so grading stays text-only.

**Rationale.** A side-channel keeps every string boundary (url4 `Payload`, peer replies, request
contexts) byte-identical for text-only runs and removes any ambiguity between data and refs.

### F3 — Canonical encoding and run scope

**Decision** (owner, 2026-10-26, review round 5; supersedes the round-4 engine-key redesign). v1 does
**not** change the engine request key ([`E/request_identity.py:13-33`][e-key]). That key exists only
while grading-accounting recorders are active; Candidate and Fusion execution set it to `None`
([`E/operation_calls.py:137-142`][e-opkey] at `main` `f70cde71b`), and grading stays text-only
(`OME-1271`), so no key the engine forms ever covers a non-text part. F3 keeps run-scoped
authorization, integrity and the canonical encoding rule below. Any change to the gateway cache key
(for example hashing decoded bytes) belongs to `OME-1681` (Khoa); **v1 requires no gateway change**.

**Authorization.** A digest is **not a bearer capability**. A blob read is scoped to *tenant + run*: a
node may read a digest only if it was ingested into the same run of the same tenant. A digest from
another run or tenant is `source_not_found`, indistinguishable from a missing blob.

**Integrity.** sha256 is verified against the ref **before storing** (ingress) and **before use** (every
read that builds a part). A mismatch is `x.blob_digest_mismatch`, permanent.

**Order (normative).** For every model-calling node whose request carries url4 attachments:

1. take the tenant and run from the run context, never from the request or the ref;
2. authorize each blob digest against that tenant + run (otherwise `source_not_found`);
3. read the bytes and verify sha256 (otherwise `x.blob_digest_mismatch`);
4. build the parts in the canonical encoding below, and only then send the request on.

A result can be reused through two **distinct** paths, and steps 1–3 precede each; each is a separate
acceptance path with its own test:

- **(a) Normal cache lookup.** The gateway's model-result cache hashes its provider-aware request DTO
  ([`G/core/request_cache/global_keys.py:265`][g-cachekey]). Authorization happens before the request
  reaches that lookup: an out-of-scope digest whose request is already cached returns
  `source_not_found` and sends no gateway request.
- **(b) Frozen-copy replay.** A frozen copy is selected by the `{kind, request, attempt}` digest plus
  `case_key` and `occurrence`, not by the cache key. Authorization also happens before any frozen-copy
  replay: an out-of-scope digest returns `source_not_found` and no frozen copy is replayed.

**Inline Case parts** (§2.7) carry their bytes in the envelope and no blob ref, so there is no tenant
+ run ref to authorize and steps 2–3 do not apply to them; they are verified and canonicalized at
import (`OME-1271`).

**Canonical encoding (normative).** Every media `data:` URI that reaches the gateway is built from
the **stored bytes** as `data:<media-type>;base64,<payload>`: the payload is standard base64 (RFC 4648
§4 alphabet, padded, no line breaks or whitespace), the media type is lowercased, and no other
parameters are present. Each part is encoded exactly once, where its bytes are turned into text:
- **url4 `attachments[]`:** the engine connector encodes the blob-store bytes.
- **v2 Case parts:** the `OME-1271` importer decodes every picture (file path or `data:` URI) to bytes,
  reads the media type from the bytes, and stores the canonical form in `cases.json` (#1554). The
  connector sends that string unchanged and does not re-encode it.
Equal files therefore produce byte-identical `data:` URIs, so equal requests produce equal gateway
request bodies with no gateway change in v1.

### F4 — "Today" is the stated snapshot

**Decision.** Section 1 and the TODAY row of the diagram describe `main` at `ec4b632b2`, where Ollama
returns 422 for file parts. Earlier behaviour (the silent drop at `637594595`) appears only as dated
history.

### 2.7 Case ingress: the v2 candidate-input envelope (`OME-1678`, #1507)

**Decision.** Adopted from khoaguin's proposal on #1450 ([comment 6286823021][khoa-v2]) and accepted in
Sergey's review of #1507 at [`29c99a31`][pr1507]. On the benchmark path a Case's pictures are
**typed content parts inside the candidate-input envelope** `screamingface.candidate-input.v2`
([`E/benchmarks/candidate_input.py`][pr-cin] in #1507). In v1 only pictures are imported and executed
(owner, 2026-10-27, review round 6); the schema's `file` (PDF) part is described below as a
future-compatible capability, not a v1 execution path:

- Parts are only `text`, `image_url` (`url`, optional `detail` of `auto` \| `low` \| `high`) and `file`
  (`file_data`, optional `filename`, `application/pdf` only; future-compatible, not imported in v1):
  the set the gateway already accepts
  ([`G/core/content_parts.py`][g-parts]), so nothing in between translates.
- Picture and file parts go in **user** messages only (Anthropic OAuth drops non-text parts from system
  messages, §1). Text-only Cases stay v1, and a v2 envelope holds at least one non-text part, so every
  Case has exactly one valid encoding.
- **Structure, not scanning.** The connector reads parts from the typed envelope, never from string
  contents, so F2's no-scanning rule holds.
- **Position.** Parts keep the position the importer wrote them in; D3 does not move them (F2).
- **Identity.** The stored Case is already canonical (the importer writes every part in the canonical
  encoding above), so the connector forwards its parts exactly as stored and does not re-encode them.
  The engine request key is unchanged (F3).
- **Only `data:` URIs.** Media parts carry inline `data:` URIs and nothing else; the gateway refuses
  any other form before its cache stage (`OME-1542`, #1479, open at this revision).
- **Limits.** The gateway's 8 MiB (8,388,608-byte) request-body cap (#1479) bounds one request: a
  larger body gets 413 `request_too_large`, permanent, before any upstream spend. Per-Case limits
  belong to the `OME-1271` importer (#1554), which refuses an oversized Case by name: at most 20
  pictures, and at most 8,000,000 bytes for the Case input with its pictures inline. That leaves room
  under the cap for the rest of an **ordinary Candidate (member) request** only (owner, 2026-10-26,
  review round 5). **Fusion residual:** a synthesis request carries the Case parts plus the member
  outputs, which the importer cannot bound; one that the member outputs push over the cap gets 413
  `request_too_large`, permanent and named, before any upstream spend. The importer does not prevent
  it. There is no per-picture limit (TableQA has a 5.21 MB picture).
- **Pictures only in v1** (owner, 2026-10-26, review round 5). The v2 schema still admits `file`
  (PDF) parts, but the `OME-1271` importer imports pictures only and refuses a PDF by name. Inline PDF
  Case parts are out of the v1 import slice; no ticket owns PDF import in v1.

**v1 gates before any v2 board ships** (from the #1507 review; read from code, not end-to-end runs):

1. **Fusion and inspect never re-serialise a v2 envelope as text.** Today a Fusion synthesizer gets
   `{"input": <v2 envelope string>, …}` ([`P/_evaluation/candidate.py:769-787`][p-fctx]), which
   `_native_messages` ([`E/world/connector.py:1495`][pr-native]) does not read as an envelope, and
   `conversation_messages` ([`I/conversation_input.py:62`][pr-conv]) re-wraps a v2 Case as v1 text; both
   would send the base64 as prompt tokens. **Enabling dependency:** `OME-1679` and `OME-1271` PR1 (the
   shared envelope parser) both block the v2 importer (`OME-1271` PR2); a v2 Case may not be imported
   before both land. The only alternative is that admission refuses Fusion candidates on v2 Cases by
   name, shipped with the importer; "imports may proceed while `OME-1679` blocks only SOTA pushes" does
   not satisfy this gate.
2. **The judge is text-only by an explicit refusal, not by accident (D6).** `_messages`
   ([`E/world/connector.py:1481`][pr-msgs]) builds parts for any v2 context; pictures are dropped today
   only because [`I/judge_provider.py:432`][i-judge] writes v1 from `message.text`. A parts message under
   `current_grading_case()` ([`E/grading_call_scope.py:43`][pr-grade]) raises `invalid_candidate_input`,
   pinned by a test.
3. **Reports show a placeholder, never base64** (`OME-1680`). `_decode_candidate_envelope`
   ([`P/case_result.py:653-680`][pr-report]) accepts only v1; the SDK `CaseResult.conversation` and the
   Report show each part as one placeholder line (type, size, sha256, filename when present). A
   placeholder never reaches a scorer. The only models that see one are a Fusion synthesizer and a
   reducer's signal calls, in the text beside the parts they are sent, without its sha256 and with its
   index (see the Fusion paragraph, F2).
4. **One `data:` URI pattern.** A conformance test, in both projects, pins the engine's `_DATA_URI_RE`
   ([`E/benchmarks/candidate_input.py:40-42`][pr-dre]) to the gateway's
   ([`G/core/content_parts.py:23-25`][g-dre]).
5. **Limits fit together.** The importer's largest encoded Case plus the request, model and parameter
   overhead fits under the gateway body cap (#1479) for an ordinary Candidate request (Fusion is the
   stated residual, Limits above), checked by a test on the importer's limit values;
   and the whole-`cases.json` memory gate (every run parses the whole file) is measured against the
   per-run memory budget. Both are owned by `OME-1271` and are enabling dependencies of the v2 importer.

## 3. Execution contract

1. **Two separate ingress paths, one representation out** (see the diagram).
   - **Case ingress (engine).** Benchmark Cases never travel in `RUN_SPEC`: it carries only `env` and
     `io_concurrency` ([`E/child_protocol.py:94-99`][e-spec94]), and the run reads Cases from the image's
     `cases.json` through the cases route ([`I/single_shot.py:799-818`][i-cases]). A Case's pictures are
     typed parts of a v2 candidate-input envelope (§2.7) that reach the connector in place (v1 imports no
     PDF parts, §2.7); they
     are not appended to `attachments[]`, never sit in the URL and never in a url4 expression. This path
     does not go through url4.
   - **url4 ingress.** A `src=` binding carrying `/blob/sha256/<hex>` or `blob:sha256/<hex>` is resolved
     at the evaluating node as a direct tenant + run store read (F1, F3) and appended to `attachments[]`. Any
     `url4://…/blob/…` ref, the node's own authority included, is `x.remote_blob_unsupported` (F1), and any
     `url4://` remote-node call (C6) is `x.remote_node_unsupported` (F1b), both before any I/O.
     An `https://` **attachment source** (a literal URL whose literal `;accept=` is exactly one attachment type, reachable without any model
     call, F1b) is pre-materialized before the
     first model call from the reachability-aware attachment manifest, through the url4 transport's
     destination guard, one flight per identity (URL, accept, guard policy); a classified result is
     hashed, written through to the tenant + run store (`OME-1540`) and appended to `attachments[]` in
     manifest preorder, and `attachments[]` is then frozen (F2). Every other `https://` source is a text
     source with today's lazy, per-occurrence semantics, unchanged.

   The engine connector turns `attachments[]` into OpenAI content parts (`image_url` / `file` with a
   `data:` URI in F3's canonical encoding); v2 envelope parts are already in that canonical shape,
   written once by the importer, and are forwarded unchanged (F3). It is the only shape the gateway
   sees. The gateway never fetches.
2. **Run-scoped, verified bytes.** Every node, retry and nested local expression in the run sees the
   same frozen `attachments[]` snapshot and reads the same stored bytes, verified on every read (F3).
3. **Who sees the file.** Every model-calling node, per F2. That replaces the text re-serialisation at
   [`P/_evaluation/candidate.py:358`][p-fusion] (`OME-1547`). The **grader stays text-only** (`OME-1271`); the
   Report and the SDK show a placeholder, never base64.
4. **Per-type policy** (`OME-1548`, `OME-1550`), decided per file before dispatch:
   - **native:** images and PDFs to models that accept them;
   - **convert to text:** office formats, reusing the GDPval readers;
   - **reject:** with a typed error (§4). A blind model is refused by name at admission (C9 `intent_error`), never degraded silently.
5. **Benchmarks pin files at build time.** Assets are baked into the benchmark image ([`I/prepare.py:8`][i-prep8]),
   so a Case never depends on a run-time fetch.
6. **Identity.** v1 changes no request key (F3). Equal files reach the gateway as byte-identical
   canonical `data:` URIs, and scoped authorization and digest verification precede both the gateway's
   normal cache lookup and any frozen-copy replay (F3 paths a and b).

## 4. Error ownership

Wrapping rule: the phase that detects a failure raises it with its own code; enclosing nodes wrap it as
a `SourceFailure` that **preserves the original code and permanence verbatim** and adds the node path. A
wrapper never turns a permanent failure into a retryable one, and only retryable failures are retried.
**One explicit cross-layer exception:** the engine connector translates the gateway's
`unsupported_content_part` into url4 `intent_error` (permanence kept, gateway `info` carried as
`cause`), because in url4 terms a model that cannot take a part is an admission condition (C9).
Codes not in url4 Spec C travel on the url4 wire with the `x.` implementation prefix (C §13.5.2) until
Kevin adopts them into the spec, as `x.admission_timeout` does today ([`U/core/errors.py:48`][u-xcode]).

| Code | Phase owner | Status | Class | Notes |
|---|---|---|---|---|
| `source_not_found` | url4 node resolver | per Spec C §13.2.5 | permanent | C5; also a digest outside the tenant + run scope (F3) |
| `x.remote_blob_unsupported` | url4 node resolver | 422 (proposed) | permanent | F1; every `url4://` blob ref; raised before any network I/O |
| `x.remote_node_unsupported` | url4 node resolver | 422 (proposed) | permanent | F1b, C6; every `url4://` remote-node call in a node context (every `Url4Node` evaluation, and everything nested in a `Client(node=…)` evaluation); the Client's own outer hop and a bare `url4.run()` are unchanged; raised before any network I/O |
| `x.source_destination_blocked` | url4 HTTP transport guard | 422 (proposed) | permanent | F1b; disallowed scheme, refused address range on any hop, or `https`→`http` downgrade; `OME-1704` |
| `x.source_redirect_limit` | url4 HTTP transport guard | 422 (proposed) | permanent | F1b; more than the configured hop limit (default 3) |
| `x.source_too_large` | url4 HTTP transport guard | 413 (proposed) | permanent | F1b; streaming cap on decoded bytes, aborted mid-stream |
| `x.source_timeout` | url4 HTTP transport guard | 504 (proposed) | retryable | F1b; connect timeout or the total deadline across all hops |
| `x.blob_digest_mismatch` | engine blob store (ingest and read) | 422 at ingest (proposed); 500 at read (proposed) | permanent | F3; at read it is store corruption, logged as such: the node fails with this code and the node path, the run ends `failed` with it, and it is never retried or served from a cache (F3 order) |
| `unsupported_content_type` | url4 bytes fetch (#1478, pre-materialization classification); engine connector (per-type policy) | per Spec C §13.5.2 | permanent | C8; on an https attachment source, a Content-Type not equal to its `;accept=` type, missing, or not one media type (no sniffing); on a text source, #1478's existing text rule, unchanged; or a type the node cannot carry or convert |
| `intent_error` | engine admission (model modality check) | 422 ([`U/peer/_http.py:52`][u-intent]) | permanent | C9; the source stays `resolved` |
| `unsupported_content_part` | gateway `check_messages` | 422 ([`G/core/content_parts.py:66-83`][g-422]) | permanent | backstop when admission misses; translated to `intent_error` with the gateway `info` as `cause`: the one named exception to the verbatim wrapping rule |
| `timeout` | whichever phase owns the deadline (resolver, connector, gateway upstream) | url4 mapping, unchanged | retryable | retried with the same frozen attachments snapshot and the same request; no re-fetch |
| `x.source_not_static` | url4 run admission (attachment manifest, `OME-1543`) | 422 (proposed) | permanent | F1b; an `https://` **attachment source** whose URL or `;accept=` is not literal in the authored expression (row-substituted, variable, model-derived or fetched-body-derived; row-derived URLs are deferred to `OME-1748`), or whose reachability depends on model execution (an enclosing iteration over a processed group, a model call, a remote expression, a nested model-dependent iteration, or a binding to one); text sources are never refused with it; raised before any fetch or model call |
| `x.attachments_too_many` | url4 run pre-materialization (`OME-1543`) | 413 (proposed) | permanent | F1b; more than 20 url4 attachments in one run; raised before any model call |
| `x.attachments_too_large` | url4 run pre-materialization (`OME-1543`) | 413 (proposed) | permanent | F1b; more than 8,000,000 aggregate decoded bytes of url4 attachments in one run; raised before any model call |
| `request_too_large` | gateway body cap (`OME-1542`, #1479) | 413 | permanent | 8 MiB request body; before any upstream spend; includes the Fusion residual (§2.7). `spec_too_large` (1 MiB `RUN_SPEC`, [`E/child_protocol.py:103-104`][e-spec103]) keeps its code |

Statuses marked *proposed* are new in this spec and need Kevin's sign-off for the url4 wire. His
recorded approval at `e61bcde` predates these codes and statuses, so it does not cover them; they stay
proposed until he signs off this revision. **Acceptance of this spec therefore requires Kevin's url4
wire approval of the exact current revision (review rounds 7–10: the grammar-facing `;accept=`
attachment opt-in, the literal-target and model-free reachability rules, and the codes, including `x.attachments_too_many`,
`x.attachments_too_large` and `x.source_not_static`); it is awaited.** `x.source_destination_blocked` and the other `x.source_*`
codes **are** active in v1, owned by the url4 HTTP transport guard (F1b). Only remote-node
authentication failure has no v1 owner, because neither remote blobs (F1) nor remote-node calls (F1b)
exist in v1; it belongs to the node-to-node authentication spec.

## 5. Boundary with `OME-1330` / `OME-1271`

| This epic (`OME-1529`): execution | `OME-1330` / `OME-1271`: benchmarks |
|---|---|
| url4 refs and their resolution; the engine run blob store, attachments and connector parts; gateway transport, the content-part gate and limits; the per-type policy; fusion receiving the parts; modality flags | Case envelope image kind; import and storage of benchmark files (inline v1, with a per-benchmark byte budget); serving; grading stays text; board choice and proofs (FigQA, TableQA, then MMMU) |

Shared representation: benchmark files use the same spec-native form. `sf-blob://` (an example in
`OME-1271`) is **not** part of url4. At most it can be an internal alias inside inspect's
`media_resolver`, mapped to `/blob/sha256/<hex>`, and it never appears in an expression or a contract.

## 6. url4 contract

Adopted **as signed off by Kevin (2026-10-13)** in `OME-1534`; the Parse column of C1 is corrected
(it is a relative URL, `RelUrl`, not a data URI), and the v1 notes apply F1 (C1, C2) and F1b (C6).

| # | Expression | Parse (B §5.2) | Resolution at the evaluating node |
| -- | -- | -- | -- |
| C1 | `(img:0.5:src=/blob/sha256/<hex>)!'Describe'` | relative URL (`RelUrl`) | direct tenant + run store read on the evaluating node (F1, F3); it is **not** rewritten to `url4://<current_node>/…`, and attribution records the relative path, which never re-enters classification; bytes go to the model as a `data:` URI (§26.2.3) |
| C2 | `(img:src=url4://n2.example/blob/sha256/<hex>)!'Describe'` | remote URL4 reference | fetched from `n2` with `url4://` semantics (§3.5). **v1: `x.remote_blob_unsupported`** for any authority, `n2` or the evaluating node itself (F1) |
| C3 | `(img:src=blob:sha256/<hex>)!'Describe'` | bare token (identifier) | resolved from the evaluating node's own store |
| C4 | `(img:'blob:sha256/<hex>')!'Describe'` | quoted text | the literal string; not resolved |
| C5 | C3 where the node doesn't hold the bytes | bare token | `source_not_found`, permanent (C §13.2.5) |
| C6 | `(url4://n2.example/v1(img:src=blob:sha256/<hex>)!'Describe')!'Summarize'` | nested remote expression | the outer node forwards the inner sources unchanged; `n2` resolves C3 against its own store. **v1: `x.remote_node_unsupported`** before any I/O, until node-to-node authentication is specified (F1b) |
| C7 | `(blob:sha256/<hex>)!'Describe'` | ParseError | `blob` reads as a name with no value-shaped binding (§4.5 disambiguation), so `src=` is required |
| C8 | resolved bytes of a type the node can't handle | n/a | `unsupported_content_type` (C §13.5.2) |
| C9 | resolved image sent to a model that can't take images | n/a | `intent_error`; the source stays `resolved` (C §13.6) |

Further rules:
- **Resolution is node by node.** A node processing an outer expression must not modify sources in nested sub-expressions (C6).
- **Inline `data:` appears only in Case envelopes, never in expressions** (`OME-1597`). Unquoted, `;` and `,` split it; quoted, it is literal text. A binary needed deeper in the tree must be a retrievable ref.
- **Port.** The IOLayer gains a bytes fetch returning `(bytes, media_type)`. `Payload` stays `str`; resolved refs become attachments (F2), never payload text (`OME-1538`).

## 7. Open items and dated observations

All rows below are manual observations; none is a guarantee or a fixture.

| Item | State |
|---|---|
| Live native PNG + PDF (runner sends text, a PNG reading `4827`, a PDF reading `ZEBRA-4127`) | **Observed 2026-10-16:** both read correctly on Antigravity `gemini-3-flash` (`inlineData`, Code Assist wire); Codex `gpt-6-astra` on a ChatGPT plus sign-in (`input_image` / `input_file`); Anthropic OAuth `claude-haiku-4-5`; OpenRouter `google/gemini-2.5-flash` and `anthropic/claude-haiku-4.5`. OpenRouter `openai/gpt-4o-mini` read the PDF but misread the PNG (`4027`): a model-quality miss, not a transport drop. |
| Ollama with PDFs | **Observed 2026-10-16** at the pre-#1447 snapshot: silent drop (`qwen2.5vl:3b`, PDF 200 with +7 tokens). At `ec4b632b2`: 422 `part_type: file` by code (#1447); a PNG still read `4827` when #1447 was verified. |
| Image and PDF token reporting | **Observed 2026-10-16/17**, input for `OME-1546`: only `prompt_tokens` moved; `prompt_tokens_details` was `null` on Antigravity. Prompt-token delta vs the text case, PNG / PDF: Antigravity +1098 / +527; Codex `gpt-6-astra` +73 / +36; Anthropic `claude-haiku-4-5` +68 / +1585; OpenRouter `gemini-2.5-flash` +1038 / +1297; Ollama `qwen2.5vl:3b` +68 / n/a. Provider- and model-version-dependent. |
| Gemini CLI (Code Assist OAuth) | Not verified, and no longer pursued: the route is deprecated (I-26). Observed 2026-10-16: the test account's Code Assist setup returned no `cloudaicompanionProject` (text fails too). It shares `core.gemini_parts` with Antigravity. |
| Codex model catalog | Stale (`OME-1634`). Observed 2026-10-16: `gpt-5.4-mini` refused for a ChatGPT plus account while `gpt-6-astra` worked; a free-plan sign-in refused for every model. PR #1441 (open at the snapshot) types that as 403 `codex_plan_unsupported`. |
| OpenAI (API key) with PDFs | Not run (no profile signed in). **UNVERIFIED.** |
| Per-provider size and count limits | **UNVERIFIED**; not measured. Needed for per-provider limit values under `request_too_large`. |
| `inspect` `media_resolver` firing on our out-of-loop scorer path | **UNVERIFIED** (`OME-1271` caveat); needs a spike before the inline-to-reference step. |
| Remote blobs | Deferred (F1); needs its own spec and ticket. |
| Remote-node calls (C6) | Disabled in v1 (F1b); need a node-to-node authentication spec; #1521's peer allowlist stays empty until then. |

[snap]: https://github.com/ScreamingFace/screamingface/tree/ec4b632b2267212783ca932c93a6c7314256ef3a
[u-text]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/core/nodes.py#L63-L66
[u-node23]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/dag/node.py#L23
[u-node70]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/dag/node.py#L70
[u-node79]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/dag/node.py#L79
[u-fetch]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/io/layer.py#L81-L85
[u-accept]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/io/layer.py#L69-L77
[u-http]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/io/http.py#L74-L80
[u-redirect]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/io/http.py#L66-L69
[u-peer]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/peer/_http.py#L109
[u-xcode]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/core/errors.py#L48
[u-intent]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/peer/_http.py#L52
[u-coll]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/dag/semantics/collection.py#L140-L142
[u-src]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/core/grammar.py#L186-L188
[u-artifact]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/streaming/protocol/signals.py#L174-L192
[u-resultdata]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/url4/src/url4/streaming/protocol/signals.py#L195-L205
[e-414]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/rest/mounts.py#L277
[e-8k]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/job_env.py#L208
[e-spec26]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/child_protocol.py#L26
[e-spec103]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/child_protocol.py#L103-L104
[e-case]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/benchmarks/case_request.py#L13-L31
[e-text]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/world/connector.py#L1535
[e-msgs]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/world/connector.py#L1478
[e-opkey]: https://github.com/ScreamingFace/screamingface/blob/f70cde71b207f14543d41b9fb160b4bc21d54d90/apps/screamingface-engine/src/screamingface_engine/operation_calls.py#L137-L142
[g-cachekey]: https://github.com/ScreamingFace/screamingface/blob/3f2b3a6efacf9b9b4604de49f49b69130b36a847/apps/aigateway/src/aigateway/core/request_cache/global_keys.py#L265-L290
[e-key]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/request_identity.py#L13-L33
[e-nltk]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/benchmarks/nltk_data.py#L38
[p-fusion]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/screamingface/src/screamingface/_evaluation/candidate.py#L358
[p-fctx]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/packages/screamingface/src/screamingface/_evaluation/candidate.py#L769-L787
[i-judge]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py#L432
[i-cap513]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/capture.py#L513
[i-cap529]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/capture.py#L529
[i-prep8]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py#L8
[i-prepin]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py#L2097-L2101
[g-parts]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py
[g-422]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L66-L83
[g-img]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L181-L197
[g-detail]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L27-L29
[g-detail2]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L200-L209
[g-pdf]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L32
[g-file]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L211-L232
[g-gem]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/gemini_provider/plugin.py#L299-L304
[g-ag]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/antigravity_provider/plugin.py#L210-L215
[g-codex]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/codex_provider/plugin.py#L129-L134
[g-oll]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/ollama_provider/plugin.py#L90-L99
[g-anth]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/anthropic_provider/chat_handler.py#L180-L197
[g-hf74]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/huggingface_provider/discovery.py#L74
[g-hf129]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/plugins/huggingface_provider/discovery.py#L129
[e-spec94]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine/child_protocol.py#L94-L99
[i-cases]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py#L799-L818
[g-dre]: https://github.com/ScreamingFace/screamingface/blob/ec4b632b2267212783ca932c93a6c7314256ef3a/apps/aigateway/src/aigateway/core/content_parts.py#L23-L25
[khoa-v2]: https://github.com/ScreamingFace/screamingface/pull/1450#issuecomment-6286823021
[pr1507]: https://github.com/ScreamingFace/screamingface/pull/1507/commits/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8
[pr-cin]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py
[pr-dre]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py#L40-L42
[pr-native]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine/world/connector.py#L1495
[pr-msgs]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine/world/connector.py#L1481
[pr-conv]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine_inspect/conversation_input.py#L62
[pr-grade]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/apps/screamingface-engine/src/screamingface_engine/grading_call_scope.py#L43
[pr-report]: https://github.com/ScreamingFace/screamingface/blob/29c99a31ffacaa462ebedfdb04b5ad89844e1ac8/packages/screamingface/src/screamingface/case_result.py#L653-L680
[pr1478-media]: https://github.com/ScreamingFace/screamingface/blob/9d32862f9587bef310fc696c717cad7d109f378c/packages/url4/src/url4/io/media.py#L240-L256
[g-img-main]: https://github.com/ScreamingFace/screamingface/blob/dd4bd9a47ad5a3af8fd283e64c6e098826df6901/apps/aigateway/src/aigateway/core/content_parts.py#L242
[g-pdf-main]: https://github.com/ScreamingFace/screamingface/blob/dd4bd9a47ad5a3af8fd283e64c6e098826df6901/apps/aigateway/src/aigateway/core/content_parts.py#L42
[pr1478-text]: https://github.com/ScreamingFace/screamingface/blob/9d32862f9587bef310fc696c717cad7d109f378c/packages/url4/src/url4/io/media.py#L213-L237
