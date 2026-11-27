---
id: OME-1938
linear_url: https://linear.app/openmined/issue/OME-1938
status: done
type: feature
priority: medium
labels: [screamingface-engine, human, design-session]
parent: OME-1299
created: 2026-11-17
closed: 2026-11-25
---

# Add the FutureX-Past and BTF-3 forecasting datasets as Benchmarks

The design ticket for the two forecasting datasets behind the paper Diverse by Reasoning
(arXiv 2608.24001): each one a local inspect Task pinned to the dataset commit the paper used,
graded in code with no judge and no web search. Both are outside contributions
(`origin="external"`).

- **FutureX-Past** landed under its own ticket, OME-1952 (PR 1897): `futurex_past` and
  `futurex_past_study`.
- **BTF-3** lands here (PR 2011): `btf3`, the 1,515 yes/no questions at the paper's commit,
  accuracy at 0.5 as the headline with the Brier score beside it.

- Design: ScreamingFace/screamingface#1868
- Spec and plan: `docs/spec/2026-11-17-btf3-local-task.md` and
  `docs/plan/2026-11-17-btf3-local-task.md`
- Ledger: `docs/work/2026-11-17-btf3-local-task.md`
