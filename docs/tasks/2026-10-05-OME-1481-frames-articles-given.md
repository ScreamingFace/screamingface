---
id: OME-1481
linear_url: https://linear.app/openmined/issue/OME-1481/build-and-score-frames-with-the-articles-given-in-the-prompt
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-05
closed: 2026-10-15
---

# Build and score FRAMES with the articles given in the prompt

Parent epic: `OME-1457`. The snapshot and its builder live on Hugging Face
(`khoaguin/frames-wikipedia-2024-09-19`, builder in `build/`); two PRs: the FRAMES Task and
its two Benchmark rows (PR 1, #1422), the example notebook (PR 2). The paid run and the e2e
golden it records are the owner's (PR 2 ledger, owner-verify).

Ledgers: `docs/work/2026-10-12-OME-1481-frames-snapshot.md` (the snapshot), `docs/work/2026-10-15-OME-1481-pr1-frames-task.md` (PR 1),
`docs/work/2026-10-15-OME-1481-pr2-frames-notebook.md` (PR 2).

- 2026-10-13: decision 10 — serve the drawn article text and drop question 77, after a
  question-by-question check of both text forms (drawn breaks 1 question, raw source 3).
- 2026-10-14: PR 1 opened — the builder, and the snapshot it produced published as
  `khoaguin/frames-wikipedia-2024-09-19` at commit `72f946d2ed571163cb3dc3bb8c1975d7c2ff710e`
  (2,521 articles, 824 question rows).
- 2026-10-14: the builder moved out of the repo into the dataset's `build/` folder, and PR
  #1402 was closed unmerged. Republished at commit `6ada7fb7acfe0f1125b17337d1783b1f51ffd975`:
  same revisions, template error text and combined reference sections dropped, and a
  `missing_templates` field naming the 259 articles that show a deleted template's stub.
- 2026-10-15: PR 1 (#1422) opened — `frames_oracle`, a local Task over the snapshot at
  `6ada7fb7`, judged by the paper's Figure 6 prompt; 822 Cases (77 and 141 left out by name);
  revision `eb27d52bf8431b07`. PR 2 opened — the `17_frames` example notebook.
