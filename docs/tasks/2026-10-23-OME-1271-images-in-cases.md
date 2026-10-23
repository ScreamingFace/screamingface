---
id: OME-1271
linear_url: https://linear.app/openmined/issue/OME-1271/image-support-benchmark-path-let-benchmark-cases-carry-images
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, human]
parent: OME-1330
created: 2026-10-23
closed:
---

# IMAGE SUPPORT - BENCHMARK PATH: Let benchmark cases carry images

Picture Benchmarks (MMMU, HLE, MathVista, LAB-Bench FigQA) carry each picture inside the Case as an
inline `data:` URI in the v2 candidate-input envelope (envelope and connector: OME-1678).

- PR 1a: the Engine's model request key reads a picture-bearing v2 context as its canonical part
  list (decoded-byte digests, not base64 spelling); text-only keys are unchanged.
  Ledger: `docs/work/2026-10-23-request-key-from-parts.md`.
- Later PRs: the inspect plugin on the shared envelope parser, then the v2 importer.
