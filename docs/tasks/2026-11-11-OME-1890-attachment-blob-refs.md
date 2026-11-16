---
id: OME-1890
linear_url: https://linear.app/openmined/issue/OME-1890/write-the-spec-for-carrying-url4-attachments-to-the-gateway-by-blob
status: in_review
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous, task]
parent: OME-1889
created: 2026-11-11
closed:
---

# Write the spec for carrying url4 attachments to the gateway by blob reference

This unit writes the design spec, `docs/spec/2026-11-11-attachment-blob-refs.md`. It contains no code.

- **Evidence:** the 2026-11-11 research doc, [Attachment memory cost: proof and storage options](https://claude.ai/artifact/USXsTTKz3VuEdjpGoyZr6k). It measured about 21 MB per parallel call in the engine and about 24 MB per request in the gateway.
- **Owner decisions (2026-11-11):**
  - Both the engine and the gateway change.
  - The size limit is 20 MB inline.
  - The gateway fetches files from the engine using a grant.
  - Inline and by-reference copies of a file share one cache key; this needs a `KEY_REVISION` bump.
  - Benchmark Case pictures stay inline.
  - The attachment cap depends on the path: 20 MB by reference, about 6 MB inline.
- **Epic:** OME-1889, a proposed epic in Triage. Irina and Kevin are tagged for scope approval.
- **Ledger:** `docs/work/2026-11-11-attachment-blob-refs.md`
