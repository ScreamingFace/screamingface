---
id: OME-1803
linear_url: https://linear.app/openmined/issue/OME-1803/image-support-refuse-a-run-at-admission-when-a-model-cant-take-pdfs
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1529
created: 2026-11-02
closed: 2026-11-05
---

# IMAGE SUPPORT: Refuse a run at admission when a model can't take PDFs

At Runner run admission, a Benchmark whose Cases carry a PDF (`file` part) refuses the run with a
permanent url4 `intent_error` naming every Candidate model whose published `/v1/models`
`input_modalities` lack `pdf`, before any chat call. It extends picture admission (C9, `OME-1548`,
#1584): the same `ModelSightReader` port and the same single read per run. An unreadable list fails
the run closed, as retryable with nothing spent (owner decision 2026-11-02, matching pictures). The
gateway's 422 `unsupported_content_part` stays the backstop (#1588). Spec: #1597 (`OME-1760`).

Ledger: `docs/work/2026-11-02-pdf-admission.md`.
