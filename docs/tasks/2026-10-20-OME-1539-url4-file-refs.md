---
id: OME-1539
linear_url: https://linear.app/openmined/issue/OME-1539/resolve-file-refs-in-url4-blobsha256-paths-url4-across-nodes-and
status: in_progress
type: feature
priority: medium
labels: [url4-engine, agentic, autonomous]
parent: OME-1529
created: 2026-10-09
closed:
---

# Resolve file refs in url4: /blob/sha256 paths, url4:// across nodes, and blob:sha256 tokens

`/blob/sha256/<hex>`, `url4://<node>/blob/sha256/<hex>` and bare `blob:sha256/<hex>` resolve at
the evaluating node through the `OME-1538` bytes port, verified against the digest. The bare
token is a `BlobRef` in the AST, distinct from quoted text, and round-trips unquoted. Nested
sources are forwarded unchanged. Amended 2026-10-21 to #1450 F1/F2: every `url4://…/blob` ref
fails `x.remote_blob_unsupported` before I/O, and a resolved file is a typed `Attachment`. Conformance cases C1–C9 (`OME-1534`) are executable tests.

Ledger: `docs/work/2026-10-20-url4-file-refs.md`. Spec: `docs/spec/2026-10-20-url4-file-refs.md`.

- 2026-10-20: implemented; draft PR opened on top of `OME-1538` (branch `OME-1539-url4-file-refs`).
- 2026-10-21: amended to #1450 F1/F2 (remote blobs refused pre-I/O; typed attachment).
