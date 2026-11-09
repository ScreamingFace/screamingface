---
id: OME-1271
linear_url: https://linear.app/openmined/issue/OME-1271/image-support-benchmark-path-let-benchmark-cases-carry-images
status: done
type: feature
priority: high
labels: [screamingface-engine, human]
parent: OME-1330
created: 2026-09-23
closed: 2026-10-27
---

# IMAGE SUPPORT - BENCHMARK PATH: Let benchmark cases carry images

Benchmark Cases carried text only, so picture Benchmarks (LAB-Bench FigQA and TableQA, MMMU,
HLE, MathVista and others) could not be imported. A picture now travels inline in the Case as a
`data:` URI in the v2 candidate-input envelope, end to end. Five PRs:

- PR 1b, one envelope parser for every reader ([#1551](https://github.com/ScreamingFace/screamingface/pull/1551)).
- PR 2, the importer saves an eval's pictures inside the Case, within the size limits
  ([#1554](https://github.com/ScreamingFace/screamingface/pull/1554)).
- PR 3, a Case Result shows a placeholder (type, size, sha256), never base64
  ([#1558](https://github.com/ScreamingFace/screamingface/pull/1558)).
- PR 4, one Case the grader can't read fails alone, not the whole run
  ([#1559](https://github.com/ScreamingFace/screamingface/pull/1559)).
- PR 5, a researcher opens a picture or file from its Case Result: the run parks each one in the
  engine's result store under its sha256 (a local engine drops them after 48 hours; a deployment
  sets no expiry yet), and the SDK fetches and
  checks it, with a
  Show picture or Save file button on each placeholder line in the report browser.

Local-stack FigQA and TableQA run and Show picture checked by the owner on 2026-10-27. Owner check
left: the dev notebook run once the stack is deployed.

Ledgers: `docs/work/2026-10-23-one-envelope-reader.md`,
`docs/work/2026-10-26-importer-saves-pictures.md`,
`docs/work/2026-10-27-results-picture-placeholders.md`,
`docs/work/2026-10-27-unreadable-case-fails-alone.md`, `docs/work/2026-10-27-media-on-demand.md`.
