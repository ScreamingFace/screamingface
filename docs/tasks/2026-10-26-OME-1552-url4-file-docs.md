---
id: OME-1552
linear_url: https://linear.app/openmined/issue/OME-1552
status: in_progress
type: docs
priority:   # copy from Linear (not read when this mirror was written)
labels: []  # copy from Linear (not read when this mirror was written)
created:    # copy from Linear
closed:
---

# OME-1552 — Document url4 file sources and blob refs in the public docs

New Learn page `/learn/url4-files` in `public-docs/`: an `https://` file URL as a url4 source
and the transport guard it passes; the local `/blob/sha256/<hex>` and `blob:sha256/<hex>` refs;
what v1 refuses (`x.remote_blob_unsupported`, `x.remote_node_unsupported`); the typed errors;
the gateway and per-Case limits; `input_modalities` on `/v1/models` and loud refusal of
unsupported parts. Every claim is marked on main, lands with an open PR, or specified only.

Source of truth: file-input spec #1450 (`OME-1535`). Parent epic `OME-1529`. PR waits until
#1450 merges. Ledger: `../work/2026-10-21-url4-file-docs.md`.
