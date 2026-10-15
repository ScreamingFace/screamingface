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

Parent epic: `OME-1457`. The snapshot and its builder live on Hugging Face
(`khoaguin/frames-wikipedia-2024-09-19`, builder in `build/`); two PRs remain: the FRAMES Task
and its two Benchmark rows (PR 1), the example notebook and golden recording (PR 2).

Ledgers: `docs/work/2026-10-12-OME-1481-frames-snapshot.md` (the snapshot), `docs/work/2026-10-15-OME-1481-pr1-frames-task.md` (PR 1).

- 2026-10-13: decision 10 — serve the drawn article text and drop question 77, after a
  question-by-question check of both text forms (drawn breaks 1 question, raw source 3).
- 2026-10-14: PR 1 opened — the builder, and the snapshot it produced published as
  `khoaguin/frames-wikipedia-2024-09-19` at commit `72f946d2ed571163cb3dc3bb8c1975d7c2ff710e`
  (2,521 articles, 824 question rows).
- 2026-10-14: the builder moved out of the repo into the dataset's `build/` folder, and PR
  #1402 was closed unmerged. Republished at commit `6ada7fb7acfe0f1125b17337d1783b1f51ffd975`:
  same revisions, template error text and combined reference sections dropped, and a
  `missing_templates` field naming the 259 articles that show a deleted template's stub.
