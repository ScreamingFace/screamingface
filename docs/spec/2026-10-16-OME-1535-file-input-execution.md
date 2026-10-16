# Spec — file input across url4, engine and gateway (`OME-1535`)

Epic `OME-1529`. Status: **draft for review** (url4: Kevin; gateway: Dmitry). Evidence re-checked
against `origin/main` at `637594595` (2026-10-16). Paths below are relative to:
`U/` = `packages/url4/src/url4/`, `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`I/` = `apps/screamingface-engine/src/screamingface_engine_inspect/`,
`P/` = `packages/screamingface/src/screamingface/`, `G/` = `apps/aigateway/src/aigateway/`.

Diagram: `docs/diagrams/file-input-path.svg` (today's path vs the target path).

## 1. Findings per layer (today)

### url4 — strings end to end

| Choke point | Evidence |
|---|---|
| The only content leaf is a string | `U/core/nodes.py:63-66` (`Text.value: str`) |
| Payloads are strings | `U/dag/node.py:23` ("Payloads are strings"), `:70` (`Payload = str \| list[str] \| SourceFailure`), `:79` (`ProcessFn` returns `str`) |
| Fetch returns text | `U/io/layer.py:81-85` (`FetchResult.body: str`, `media_type` kept); `U/io/http.py:74,80` (`response.text`, so binary is decoded as text) |
| Peer replies are text | `U/peer/_http.py:109` (`text/plain; charset=utf-8`) |
| Collections take a closed set of text types | `U/dag/semantics/collection.py:140-142` |
| `;accept=` is carried but no adapter honours it | `U/io/layer.py:69-77` |

Parser behaviour, reproduced with `url4.core.grammar.parse`:

- `(img:src=data:image/png;base64,AAAA)!'d'` → `ParseError` ("invalid execution-annotation key 'base64'").
- `('data:image/png;base64,AAAA')!'d'` → `Text` (a literal; never resolved).
- `(img:src=blob:sha256/ab)!'d'` → `Binding(value=Text('blob:sha256/ab'))`. It parses, but nothing resolves it yet (`OME-1539`).
- `(blob:sha256/ab)!'d'` → `ParseError` ("bare-token data binding requires 'src='"). Matches C7.

Reusable: `FetchResult.media_type`, the `;accept=` annotation, and `ResultArtifact`
(sha256 + size + media type, `U/streaming/protocol/signals.py:174`) as a pass-by-reference pattern.

### Engine — text only, non-text content refused

| Choke point | Evidence |
|---|---|
| Sync surface: 8 KiB target cap | `E/rest/mounts.py:277` (414 `uri_too_long`), `E/job_env.py:208` (`MAX_DIRECT_TARGET_BYTES = 8 * 1024`) |
| Run spec: 1 MiB cap | `E/child_protocol.py:26,103-104` (`MAX_SPEC_BYTES`, `spec_too_large`) |
| Case input becomes a string | `E/benchmarks/case_request.py:13-31` (dict → `json.dumps`) |
| Chat envelope refuses non-text content | `E/world/connector.py:1531-1532` (`invalid_candidate_input`, "content must be text"; the ticket's `:1116-1124` has moved) |
| Messages are built from strings | `E/world/connector.py:1475` (`_messages(context: str \| None, intent: str \| None)`) |
| Fusion gets the Case re-serialised as text | `P/_evaluation/candidate.py:358` (`struct({"input": …, "outputs": …})`), `:779-787` |
| Request identity hashes a string context | `E/request_identity.py:13-26` |
| Judge sees text only | `I/judge_provider.py:409` (`{"role": role, "content": message.text}`) |
| Inspect capture refuses images and audio | `I/capture.py:513,529` ("non-text content") |
| Benchmark assets are built into the image, and Runner Jobs have no egress | `I/prepare.py:8` ("Run at IMAGE BUILD time … a Job's rootfs is read-only"); `E/benchmarks/nltk_data.py:38` ("read-only rootfs and no network egress"). The ticket's `benchmarks/ifeval/grading.py:28` no longer exists. |

Fixed since the 2026-10-07 research: `I/prepare.py:1629-1633` now refuses a non-text,
non-list `sample.input` (`PrepareError`) instead of taking `str()` of it.

### Gateway — native media for the custom adapters (`OME-1541`, merged in #1431)

- `G/core/content_parts.py` parses OpenAI `content` into text, inline media (`MediaPart`) and
  `RemoteImagePart`. Anything a provider cannot carry is refused before dispatch with a typed
  **422 `unsupported_content_part`** (`:66`), raised in each plugin's `prepare_chat_body`
  (`G/plugins/{gemini,antigravity,codex}_provider/plugin.py`, `check_messages`).
- Accepted: `image_url` must be `image/*` (`:174-191`), with `detail` limited to `auto|low|high`
  (`:29,193-201`); `file` must be `application/pdf` (`:32,204-216`). Untyped non-text parts are refused.
- Gemini and Antigravity: `inlineData`; remote image URLs are refused with `reason: remote_url` (the gateway never fetches).
- Codex: `input_text` / `input_image` / `input_file`; https image URLs are passed through, since OpenAI fetches them.
- Ollama (`OME-1641`, PR #1447, open): LiteLLM's `ollama_chat` conversion keeps `image_url` parts and silently
  drops `file` parts (live: PDF answered 200 with +7 prompt tokens and an unrelated answer). The Ollama plugin
  now runs the same gate with `allow_files=False` and `allow_remote_images=False`: a PDF or a remote image URL
  gets 422 `unsupported_content_part`; data-URI images are unchanged. PDF-to-text for Ollama stays with `OME-1550`.
- Still open:
  - **No request body cap** anywhere in the gateway (no match for a body or content-length limit under `G/` outside `api_key_validation_http.py` and `object_store.py`). → `OME-1542`
  - **Anthropic OAuth drops non-text system parts:** `G/plugins/anthropic_provider/chat_handler.py:180-193` keeps only `type == "text"`. → `OME-1542`
  - **`/v1/models` carries no input-modality field.** Only HuggingFace discovery parses `input_modalities` (`G/plugins/huggingface_provider/discovery.py:74,129`), and nothing exposes it. → `OME-1537`
  - **SSRF:** LiteLLM may fetch caller `http(s)` image URLs for the pass-through providers (Anthropic, OpenRouter). **UNVERIFIED** in this pass; it comes from the 2026-10-07 research. Ollama refuses remote URLs once #1447 merges. → `OME-1542`

## 2. Execution contract

1. **Two ways in, one representation out.** The engine connector accepts:
   - **inline `data:` parts** for benchmark Cases (`OME-1271` v1). Case content travels as `$input` in the run spec, within the **1 MiB** `RUN_SPEC` cap, never in the URL (8 KiB cap);
   - **blob refs** for url4 sources and client uploads: `/blob/sha256/<hex>`, `url4://<node>/blob/sha256/<hex>`, and `blob:sha256/<hex>` (§4).

   The connector resolves both into OpenAI content parts (`image_url` / `file` with a `data:` URI), and that is the only shape the gateway sees.
2. **Fetch once, pin.** A remote source is fetched once per run. Its bytes are pinned by sha256 into the run's blob store, and every later use, retry and node in the run reads the pinned bytes. The gateway never fetches.
3. **Who sees the file.** Every ensemble member and the fusion synthesizer receive the real file parts. That means replacing the text re-serialisation at `P/_evaluation/candidate.py:358` (`OME-1547`). The **grader stays text-only** (`OME-1271`); the Report and the SDK show a placeholder, never base64.
4. **Per-type policy** (`OME-1548`, `OME-1550`), decided per file before dispatch:
   - **native:** images and PDFs to models that accept them;
   - **convert to text:** office formats, reusing the GDPval readers;
   - **reject:** with a named 4xx. A blind model is refused by name at admission (C9 `intent_error`), never degraded silently.
5. **Benchmarks pin files at build time.** Assets are baked into the benchmark image (`I/prepare.py:8`). Runner Jobs have a read-only rootfs and no egress (`E/benchmarks/nltk_data.py:38`), so a Case may not depend on a run-time fetch.
6. **Identity.** The request key hashes the file digest, not the bytes or a URL (`E/request_identity.py`). A changed remote file is therefore a different request.

## 3. Boundary with `OME-1330` / `OME-1271`

| This epic (`OME-1529`): execution | `OME-1330` / `OME-1271`: benchmarks |
|---|---|
| url4 refs and their resolution; the engine blob store and connector parts; gateway transport, the content-part gate and limits; the per-type policy; fusion receiving the parts; modality flags | Case envelope image kind; import and storage of benchmark files (inline v1, with a per-benchmark byte budget); serving; grading stays text; board choice and proofs (FigQA, TableQA, then MMMU) |

Shared representation: benchmark files use the same spec-native form. `sf-blob://` (an example in
`OME-1271`) is **not** part of url4. At most it can be an internal alias inside inspect's
`media_resolver`, mapped to `/blob/sha256/<hex>`, and it never appears in an expression or a contract.

## 4. url4 contract

Adopted **as signed off by Kevin (2026-10-13)** in `OME-1534`, verbatim:

| # | Expression | Parse (B §5.2) | Resolution at the evaluating node |
| -- | -- | -- | -- |
| C1 | `(img:0.5:src=/blob/sha256/<hex>)!'Describe'` | relative data URI | `url4://<current_node>/blob/sha256/<hex>` with §5.4.2 policy, identity and attribution; bytes go to the model as a `data:` URI (§26.2.3) |
| C2 | `(img:src=url4://n2.example/blob/sha256/<hex>)!'Describe'` | remote URL4 reference | fetched from `n2` with `url4://` semantics (§3.5) |
| C3 | `(img:src=blob:sha256/<hex>)!'Describe'` | bare token (identifier) | resolved from the evaluating node's own store |
| C4 | `(img:'blob:sha256/<hex>')!'Describe'` | quoted text | the literal string; not resolved |
| C5 | C3 where the node doesn't hold the bytes | bare token | `source_not_found`, permanent (C §13.2.5) |
| C6 | `(url4://n2.example/v1(img:src=blob:sha256/<hex>)!'Describe')!'Summarize'` | nested remote expression | the outer node forwards the inner sources unchanged; `n2` resolves C3 against its own store |
| C7 | `(blob:sha256/<hex>)!'Describe'` | ParseError | `blob` reads as a name with no value-shaped binding (§4.5 disambiguation), so `src=` is required |
| C8 | resolved bytes of a type the node can't handle | n/a | `unsupported_content_type` (C §13.5.2) |
| C9 | resolved image sent to a model that can't take images | n/a | `intent_error`; the source stays `resolved` (C §13.6) |

Further rules:
- **Resolution is node by node.** A node processing an outer expression must not modify sources in nested sub-expressions (C6).
- **Inline `data:` appears only in Case envelopes, never in expressions** (`OME-1597`). Unquoted, `;` and `,` split it; quoted, it is literal text. A binary needed deeper in the tree must be a retrievable ref.
- **Port.** The IOLayer gains a bytes fetch returning `(bytes, media_type)`. `Payload` stays `str`, and refs travel as text (`OME-1538`).

## 5. Open items

| Item | State (2026-10-16) |
|---|---|
| Live native PNG + PDF (runner sends text, a PNG reading `4827`, a PDF reading `ZEBRA-4127`) | **Verified live** (2026-10-16), both read correctly on: Antigravity `gemini-3-flash` (`inlineData`, Code Assist wire); Codex `gpt-6-astra` on a ChatGPT plus sign-in (`input_image` / `input_file`); Anthropic OAuth `claude-haiku-4-5`; OpenRouter `google/gemini-2.5-flash` and `anthropic/claude-haiku-4.5`. OpenRouter `openai/gpt-4o-mini` read the PDF but misread the PNG (`4027`): a model-quality miss, not a transport drop. |
| Ollama with PDFs | Silent drop found live (`qwen2.5vl:3b`, PDF 200 with +7 tokens). Fixed by `OME-1641` (PR #1447, open): PDF → 422 `part_type: file`; PNG still reads `4827`. |
| Image and PDF token reporting | Only `prompt_tokens` moves; `prompt_tokens_details` is `null` on Antigravity, so there is no per-modality breakdown. Prompt-token delta vs the text case, PNG / PDF: Antigravity +1098 / +527; Codex `gpt-6-astra` +73 / +36; Anthropic `claude-haiku-4-5` +68 / +1585; OpenRouter `gemini-2.5-flash` +1038 / +1297; Ollama `qwen2.5vl:3b` +68 / n/a. Input for `OME-1546`. |
| Gemini CLI (Code Assist OAuth) | Not verified, and no longer pursued: the route is deprecated (I-26). The test account's Code Assist setup returned no `cloudaicompanionProject` (text fails too). It shares `core.gemini_parts` with Antigravity, which is verified. |
| Codex model catalog | Stale (`OME-1634`): `gpt-5.4-mini` is refused for a ChatGPT account even on the plus plan, while `gpt-6-astra` works. A free-plan sign-in is refused for every model; PR #1441 (open) types that as 403 `codex_plan_unsupported`. |
| OpenAI (API key) with PDFs | Not run (no profile signed in). **UNVERIFIED.** |
| Per-provider size and count limits | **UNVERIFIED**; not measured. |
| `inspect` `media_resolver` firing on our out-of-loop scorer path | **UNVERIFIED** (`OME-1271` caveat); needs a spike before the inline-to-reference step. |
