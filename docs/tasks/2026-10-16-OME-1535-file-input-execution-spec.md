---
id: OME-1535
linear_url: https://linear.app/openmined/issue/OME-1535/write-the-file-input-execution-spec-for-the-engine-and-gateway
status: in_review
type: docs
priority: high
labels: [repo-dev-processes, human, autonomous]
parent: OME-1529
created: 2026-10-09
closed:
---

# OME-1535 — Write the file-input execution spec for the engine and gateway

Execution spec for epic OME-1529: per-layer findings (url4, engine, gateway) re-checked on
`main`, the execution contract, the boundary with OME-1330 / OME-1271, the url4 contract
(OME-1534 C1–C9) and the open items with the 2026-10-16 live provider evidence.

Spec: ../spec/2026-10-16-OME-1535-file-input-execution.md ·
Ledger: ../work/2026-10-16-file-input-execution-spec.md

Current decisions (review round 5, 2026-10-26): `https://` sources pre-materialized before the first
model call (fetch identity URL + accept, single-flight) and `attachments[]` frozen; per-run caps of 20
attachments and 8,000,000 decoded bytes (`OME-1543`); no engine-key change in v1, canonical `data:`
encoding with authorization before both the gateway cache lookup and frozen-copy replay; Case parts
canonicalized once by the `OME-1271` importer (pictures only in v1) and forwarded unchanged; Fusion gets
the media parts plus index-only, digest-free placeholders; Case-ingress headroom holds for ordinary
Candidate requests, Fusion may get 413 `request_too_large`; C6 refused in a node context. The `x.*`
codes await Kevin's url4 wire approval.
