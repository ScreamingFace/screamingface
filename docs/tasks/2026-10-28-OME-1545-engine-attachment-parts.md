---
id: OME-1545
linear_url: https://linear.app/openmined/issue/OME-1545/image-support-url4-path-build-image-and-file-content-parts-in-the
status: in_review
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-09
closed:
---

# Build image and file content parts in the engine connector

Every model call (members, synthesizers, reducers) turns the run's frozen url4 `attachments[]` into
OpenAI content parts on the last user message, before the text (spec #1450 / `OME-1535` F2/F3):
`image/*` → `image_url`, anything else → `file`, canonical `data:` URIs, sha256 verified before send.
Calls with no attachments are byte-identical; a grading call carrying attachments is refused with
`invalid_candidate_input`. Bytes come from the url4 snapshot or a run-scoped `BlobReader` port.

Parent `OME-1681` (epic `OME-1529`). Depends on `OME-1543` (#1587).
Ledger: `../work/2026-10-28-engine-attachment-parts.md`.
