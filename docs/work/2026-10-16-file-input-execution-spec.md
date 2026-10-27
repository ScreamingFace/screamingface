---
ticket: OME-1535
stack: repo
status: in_progress
started: 2026-10-16
finished:
---

# file-input-execution-spec — the file-input execution spec for the engine and gateway

## Intent

Write the execution spec that the engine and gateway leaves of epic `OME-1529` build against:
per-layer findings re-verified on current `main`, the execution contract, the boundary with
`OME-1330` / `OME-1271`, the url4 contract (`OME-1534` C1–C9 as signed off) and the open items
with the 2026-10-16 live evidence. Docs only.

## Planned changes

- `docs/spec/2026-10-16-OME-1535-file-input-execution.md` (new)
- `docs/diagrams/file-input-path.svg` + `.png` (new)
- `docs/tasks/2026-10-16-OME-1535-file-input-execution-spec.md` (mirror)

## Test plan

- Every file:line cited re-checked against `origin/main` at `637594595` (40 citations, 37 unique; 0 wrong).
- url4 parse behaviour reproduced with `url4.core.grammar.parse`.
- Diagram rendered with `rsvg-convert` and inspected.
- Review round 1 (HupBaHa, 2026-10-21): every citation refreshed to `ec4b632b2` and rewritten as a
  commit-qualified link; each link's line range checked against `git show ec4b632b2:<path>`.

## Acceptance

- The spec is merged, and Kevin (url4) and Dmitry (gateway) have reviewed it.
- The spec awaits Kevin's url4 wire approval of this revision: the `x.*` codes and statuses in §4
  are proposed, and his `e61bcde` approval predates them.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the branch (`docs(spec): draft the file-input execution spec`).
- **Gates:** docs only; no app gates apply.
- **Deviations:** rebased on `637594595` and updated for OME-1541 (#1431), the Ollama file-part
  refusal (OME-1641, #1447), the 2026-10-16 live provider results, the Gemini CLI deprecation (I-26) and
  the stale Codex catalog (OME-1634). Items marked UNVERIFIED in the spec were not re-run.
- **Review round 1 (2026-10-21):** rebased on `ec4b632b2` (#1447 merged). Owner decisions F1–F4
  (locked by Sergey 2026-10-21) written in as normative §2: remote blobs deferred
  (`remote_blob_unsupported`, bar for a remote-blob spec), the `attachments[]` side-channel, the
  canonical content-part request identity with tenant + run blob scope and sha256 verification, and
  the TODAY snapshot. Added the error-ownership table (§4), separate Case and url4 ingress paths,
  the `ResultArtifact`/`ResultData` and `RelUrl` corrections, and dated-observation labels. The
  diagram was regenerated (title/desc, ≥ 12 px labels, embedded in the spec).
- **Review round 2 (2026-10-21):** owner decisions D1–D6 folded into F1/F2. D1 made explicit: every
  `url4://` blob ref is remote in v1 (no self-recognition; `url4://<self>` dropped from url4 ingress and
  the diagram), only authority-less refs are local. D3 (attachments on the last user message), D4
  (a text blob read as a collection is text, not an attachment) and D5 (a failed `;optional` blob
  source fails the run) added as normative text; D2/D6 were already in F2. New url4 wire codes spelled
  with the `x.` prefix (`x.remote_blob_unsupported`, `x.blob_digest_mismatch`), matching `#1482` and
  `x.admission_timeout` at `ec4b632b2`. Diagram PNG re-rendered with `rsvg-convert`.
- **Review round 3 (2026-10-21):** adopted khoaguin's v2 candidate-input envelope (#1450 comment
  6286823021) as new §2.7, per Sergey's #1507 review: Case parts are typed parts in
  `screamingface.candidate-input.v2`, read structurally, keeping their position; identity via the raw
  `context` hash; `data:` URIs only; the gateway 8 MiB body cap (#1479) bounds a request and per-Case
  limits belong to the `OME-1271` importer. §3 Case ingress corrected: `RUN_SPEC` carries only `env`
  (`child_protocol.py:94-99`) and Cases come from `cases.json` (`single_shot.py:799-818`), not appended
  to `attachments[]`. D3 scoped to url4 attachments merged into an envelope. Four v1 gates recorded
  (Fusion/inspect re-serialisation `OME-1679`/`OME-1271` PR1, explicit judge refusal D6, Report
  placeholder `OME-1680`, `data:` pattern conformance test). Diagram regenerated: Case ingress is now
  `cases.json` → v2 envelope (§2.7) straight into the engine connector; only url4 refs feed
  `attachments[]`; PNG re-rendered with `rsvg-convert`.
- **Review round 4 (2026-10-21, HupBaHa CHANGES_REQUESTED at `a6d53fb5`):** owner decisions of the
  same day applied. (1) C6 remote-node calls disabled in v1: refused by the resolver with
  `x.remote_node_unsupported` before any I/O until a node-to-node authentication spec exists; #1521's
  peer allowlist stays empty and must not be populated. (2) One request identity: the canonical ordered
  part list plus model, params and adapter revision; a v2 envelope is normalized to it before keying;
  §2.7 no longer claims the raw `context` suffices. Also: C1 is a direct tenant + run store read, never
  rewritten to `url4://<self>/…`; F3 gains a normative order (run scope → authorize → read + verify →
  canonical parts → cache / frozen-copy lookup, hit and miss); the v2 importer gate is a hard enabling
  dependency (`OME-1679` + `OME-1271` PR1, or Fusion refused at admission) plus a limits-fit gate;
  §4 corrected (the `x.source_*` codes are active in v1, Kevin's `e61bcde` approval predates them,
  read-time digest mismatch is 500 / run `failed`). Diagram gains the https ingress → transport guard →
  store write-through row and the C6 refusal; PNG re-rendered with `rsvg-convert`. Linear bodies stale
  vs the spec are listed in the PR comment for the owner (not edited here).
- **Owner decision Q-B (2026-10-22, `OME-1543` comment "Owner decisions"):** the grammar does not
  preserve `src=` (`(src=https://a)` and `(https://a)` parse to the same `Url`, `grammar.py:186-188`),
  so F1b's "only an `https://` value in a `src=` binding is fetched at run start" is replaced:
  `https://` sources stay lazy text fetches as today; a non-text body is hashed into the tenant+run
  store (write-through) and appended to `attachments[]` at its source position; a text body is
  unchanged and exempt from D5. F2 structure rule, Propagation and §3 url4 ingress aligned; diagram
  https row and description updated, PNG re-rendered with `rsvg-convert`.
- **Interpretations to confirm in review:** the judge uses the F2 builder but receives no
  attachments under `OME-1271` v1; a remote nested expression (C6), once enabled, does not receive the outer run's
  attachments; a request with no non-text part keeps today's key (adapter revision enters only
  multimodal keys, so text keys and frozen copies stay valid; superseded in round 5: v1 changes no
  engine key); new codes travel with the url4 `x.` prefix until Spec C adopts them.
- **F3 scope narrowed (2026-10-26, Sergey's reply to khoaguin's inline F3 comment on #1450):** F3 is the
  engine's own request identity. Step 5 no longer implies the engine key decides gateway cache hits: the
  model-result cache and frozen copies are keyed in the gateway from the raw body (`global_keys.py`);
  the engine key is the grading-accounting join key (`operation_calls.py:138`,
  `grading_accounting.py:79`), cited at `main` `3f2b3a6ef`. New normative **canonical encoding** rule:
  every `data:` URI the connector sends (url4 attachments and v2 Case parts) is rebuilt from stored bytes
  as padded RFC 4648 §4 base64 with no whitespace, a lowercased media type and no extra parameters, so
  equal files share one gateway cache entry with no gateway change; for Case parts the `OME-1271`
  importer applies it (#1554; the earlier #1550 closed unmerged). The adapter-revision key text is
  superseded in round 5.
- **Fusion representation (2026-10-26, `ebc28df30`):** the Fusion synthesizer (and a reducer's signal
  calls) gets every Case media part, in Case order, before the `{input, outputs}` / `{input, panel}`
  text; in that text each part is a placeholder with its 1-based index among the parts sent, media
  type, size and filename, and **no digest**; human-facing placeholders (Report, SDK) keep the sha256.
  Text-only bytes are unchanged.
- **Canonicalization at import (2026-10-26, `910d24ca6`):** the `OME-1271` importer (#1554) decodes
  every picture and writes the canonical `data:` URI into `cases.json`; the connector forwards it
  unchanged. Per-Case limits from #1554: at most 20 pictures and 8,000,000 bytes.
- **C6 node context (2026-10-26, `002699261`, #1482):** `x.remote_node_unsupported` applies in a node
  context: every `Url4Node` evaluation and, inside `Client(node=…)`, everything but the client's own
  outer hop; a bare library `url4.run()` is unchanged.
- **Review round 5 (2026-10-26, HupBaHa CHANGES_REQUESTED at `002699261`; owner decisions of the same
  day):** (1) F1b/F2: every `https://` source is pre-materialized before the first model call (fetch
  identity URL + accept, single-flight, one binary-safe classifying fetch), non-text results appended
  in source order, then `attachments[]` frozen for every node, sibling, nested expression and retry;
  failed `;optional` https sources are omitted and logged, required ones fail the run before any model
  call. (2) F3: the engine-key redesign is removed (the key exists only under grading-accounting
  recorders, `operation_calls.py:137-142` at `f70cde71b`); F3 keeps scope, integrity and canonical
  encoding, with authorization before the normal gateway cache lookup and before frozen-copy replay as
  two separate acceptance paths; inline Case parts have no ref to authorize; any gateway cache-key
  change is `OME-1681`. (3) Per-run url4 attachment caps (20, 8,000,000 decoded bytes, `OME-1543`,
  `x.attachments_too_many` / `x.attachments_too_large`); the Case-ingress headroom is narrowed to
  ordinary Candidate requests with the Fusion 413 residual stated; inline PDF Case parts are out of the
  v1 import slice. (4) §3 no longer says v2 parts are re-encoded; the `unsupported_content_part` →
  `intent_error` translation is the named exception to the verbatim-wrapper rule; the code is
  `request_too_large` everywhere; acceptance awaits Kevin's url4 wire approval. Diagram https row and
  connector label updated; PNG re-rendered with `rsvg-convert`. Linear: `OME-1543` / `OME-1544` bodies
  patched; `OME-1540` (Khoa) commented, not edited.
- **Round 5 follow-up (owner, 2026-10-26):** F1b classification made normative: Content-Type reduced
  by #1478's `bare_media_type`; media iff `image/png|jpeg|gif|webp` or `application/pdf` (a subset of
  the gateway gate, `image/*` + `application/pdf`); text iff `text/*` or a url4 collection text type;
  anything else or a missing type → `unsupported_content_type` (C8); no byte sniffing. Caps confirmed
  to count the whole `attachments[]` (local blob refs plus https media).
- **Review round 6 (2026-10-27, HupBaHa CHANGES_REQUESTED at `95108819c`; owner decisions of
  2026-10-27):** (1) F1b static source manifest: run admission compiles every authored group, body
  and fragment recursively and collects every https target with its `accept`; a target known only
  after substitution or derived from a model output or fetched body is refused with
  `x.source_not_static` before any fetch or model call. (2) One materialization record per
  (URL, accept): the whole retry sequence inside one shared flight, run-level guard policy, required
  wins, all-optional omitted, one attachment per identity at its first manifest-preorder position.
  Classification: `bare_media_type()` returning `None` is a refusal. (3) v1 Case execution is
  pictures-only in §2.7 and §3; the `file` part stays future-compatible; SVG description updated, PNG
  re-rendered with `rsvg-convert`. (4) Acceptance reworded to a future condition; `OME-1544` C6 text
  patched to the node-context rule; `OME-1540` update requested from Khoa.
- **Review round 7 (2026-10-27, HupBaHa CHANGES_REQUESTED at `96727acc8`; owner decisions of
  2026-10-27):** F1b now uses an explicit attachment opt-in through the existing `;accept=` annotation
  (media ranges from `image/*`, `image/png|jpeg|gif|webp`, `application/pdf` only). Every other https
  source is a text source with today's lazy, per-occurrence `GuardNode` semantics and #1478's text
  rule, so text-only expressions are byte-identical. For attachment sources: a reachability-aware
  manifest (non-model collections resolved first; zero rows, no I/O); `x.source_not_static` narrowed
  to model- or fetched-body-derived attachment targets; identity `(URL, accept, ;optional, ;t=,
  ;retry=)` with one flight and one attachment per identity at its first manifest-preorder position
  ("required wins" dropped); type must be in the attachment set and match `;accept=`, a missing type
  is refused. Caps unchanged. Conformance cases pinned. §4 `x.remote_node_unsupported` row limited to
  node contexts; the `OME-1540` `src=` and old-F3 clauses are marked superseded in F1b pending Khoa;
  the `OME-1535` body no longer says Cases travel in `RUN_SPEC`. SVG updated, PNG re-rendered.
- **Review round 8 (2026-10-27, HupBaHa CHANGES_REQUESTED at `357ce4199`; owner decisions of
  2026-10-27):** (1) An attachment source's `;accept=` is exactly one lower-case type from
  `image/png|jpeg|gif|webp` or `application/pdf`. There is no wildcard and no list, because url4
  execution values admit neither `*` nor a comma. The response type must equal it. (2) Attachment URLs
  substituted from rows of an admitted non-model collection input (including an https JSON/NDJSON
  collection) are allowed; any other fetched-body or model derivation is `x.source_not_static`. The
  §4 row is aligned and positive and negative cases are added. (3) The `OME-1540` note now says the
  ticket matches (Sergey patched it); the `OME-1543` blocked-by `OME-1538` relation was added by
  Sergey; the `OME-1544` and `OME-1543` bodies are patched. (4) Kevin's approval is asked for rounds 7
  and 8. SVG updated, PNG re-rendered.
- **Round 9 (owner, 2026-10-27, author-side correction found while implementing `OME-1543`):** url4's
  grammar cannot express a row-derived attachment URL. `https://h/$item` is fetched literally, and
  `src=$item;accept=…` is a variable source that yields row text and ignores `;accept=`. So v1
  attachment URLs and `;accept=` are literal only; anything else is `x.source_not_static` before any
  fetch. The reachability rule stays: a body over zero rows does no I/O. The round-8 positive
  row-derived case is replaced by a literal-source-in-iteration case. Row-derived URLs are deferred to
  `OME-1748` (improvement-ideas). SVG description updated, PNG re-rendered.
- **Review round 10 (2026-10-27, HupBaHa CHANGES_REQUESTED at `895e24b8e`; owner decision of
  2026-10-27, confirming the `OME-1543` reading):** an attachment source is also
  `x.source_not_static` when any enclosing iteration's collection depends on model execution (a
  processed group, a model call, a remote expression, a nested model-dependent iteration, or a
  binding to one). Cases added: a model-produced collection that turns out empty and one that turns
  out non-empty are both refused before any I/O. §4 row and §3.1 aligned. The sign-off now requires
  Kevin's approval of the exact current revision (rounds 7–10).
