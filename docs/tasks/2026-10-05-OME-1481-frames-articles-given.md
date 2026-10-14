---
id: OME-1481
linear_url: https://linear.app/openmined/issue/OME-1481/build-and-score-frames-with-the-articles-given-in-the-prompt
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-05
closed:
---

# Build and score FRAMES with the articles given in the prompt

Parent epic: `OME-1457`. Three PRs: the snapshot builder (PR 1), the FRAMES Task and its two
Benchmark rows (PR 2), the example notebook and golden recording (PR 3).

Ledger: `docs/work/2026-10-12-OME-1481-pr1-frames-snapshot-builder.md` (PR 1).

- 2026-10-13: decision 10 — serve the drawn article text and drop question 77, after a
  question-by-question check of both text forms (drawn breaks 1 question, raw source 3).
- 2026-10-14: PR 1 opened — the builder, and the snapshot it produced published as
  `khoaguin/frames-wikipedia-2024-09-19` at commit `72f946d2ed571163cb3dc3bb8c1975d7c2ff710e`
  (2,521 articles, 824 question rows).
