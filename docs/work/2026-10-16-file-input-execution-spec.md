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
- **Interpretations to confirm in review:** the judge uses the F2 builder but receives no
  attachments under `OME-1271` v1; a remote nested expression (C6) does not receive the outer run's
  attachments; a request with no attachments keeps today's key; new codes travel with the url4 `x.`
  prefix until Spec C adopts them.
