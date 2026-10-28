---
id: OME-1552
linear_url: https://linear.app/openmined/issue/OME-1552/document-url4-file-sources-and-blob-refs-in-the-public-docs
status: in_review
type: docs
priority: medium
labels: [blocked, url4-engine, agentic, autonomous]
created: 2026-10-09
closed:
---

# OME-1552 — Document url4 file sources and blob refs in the public docs

New Learn page `/learn/url4-files` in `public-docs/`: an `https://` file URL as a url4 source
and the transport guard it passes; the local `/blob/sha256/<hex>` and `blob:sha256/<hex>` refs;
what v1 refuses (`x.remote_blob_unsupported`, `x.remote_node_unsupported`); the typed errors;
the gateway and per-Case limits; `input_modalities` on `/v1/models` and loud refusal of
unsupported parts. Every claim is marked on main, lands with an open PR, or specified only.

Source of truth: file-input spec #1450 (`OME-1535`), merged as `638be5024`. Parent epic
`OME-1529`. Ledger: `../work/2026-10-21-url4-file-docs.md`.
