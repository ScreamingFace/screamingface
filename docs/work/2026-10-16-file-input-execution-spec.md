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
  multimodal keys, so text keys and frozen copies stay valid); new codes travel with the url4 `x.`
  prefix until Spec C adopts them.
- **F3 scope narrowed (2026-10-26, Sergey's reply to khoaguin's inline F3 comment on #1450):** F3 is the
  engine's own request identity. Step 5 no longer implies the engine key decides gateway cache hits: the
  model-result cache and frozen copies are keyed in the gateway from the raw body (`global_keys.py`);
  the engine key is the grading-accounting join key (`operation_calls.py:138`,
  `grading_accounting.py:79`), cited at `main` `3f2b3a6ef`. New normative **canonical encoding** rule:
  every `data:` URI the connector sends (url4 attachments and v2 Case parts) is rebuilt from stored bytes
  as padded RFC 4648 §4 base64 with no whitespace, a lowercased media type and no extra parameters, so
  equal files share one gateway cache entry with no gateway change; applies to #1550 (`OME-1271`) for
  Case parts. Adapter revision still enters the key only with a non-text part.
