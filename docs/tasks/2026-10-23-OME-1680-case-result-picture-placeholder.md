---
id: OME-1680
linear_url: https://linear.app/openmined/issue/OME-1680/image-support-benchmark-path-show-a-placeholder-instead-of-base64-for
status: done
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1271
created: 2026-10-20
closed: 2026-10-23
---

# IMAGE SUPPORT - BENCHMARK PATH: Show a placeholder instead of base64 for pictures in Case results

A picture Benchmark's Case carries its pictures inline as `data:` URIs in the v2 candidate-input
envelope (OME-1678). The SDK's Case Result view read only v1, so a picture Case showed as raw
base64.

- `CaseResult.conversation` reads v2: text parts stay text; each picture or file part becomes one
  line such as `chart.png · image/png · 300 KB · sha256 9f86d081…`.
- Both picture forms render the same line: a `data:` URI (the SDK measures size and digest) and the
  placeholder object the engine will write in its place (OME-1679).
- Text-only results render as before. An unknown version of the envelope shows one line asking
  to upgrade screamingface, never its base64; input outside the envelope family renders as written.
- A conformance test pins the SDK's schema names to the engine's `benchmarks/contract.py`.

Ledger: `docs/work/2026-10-23-case-result-picture-placeholder.md`.
