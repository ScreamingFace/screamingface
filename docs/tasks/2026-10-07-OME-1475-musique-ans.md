---
id: OME-1475
linear_url: https://linear.app/openmined/issue/OME-1475/build-and-score-the-musique-benchmark
status: in_progress  # Linear: In Progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-05
closed:
---

# Build and score the MuSiQue benchmark

Register MuSiQue-Ans (the 2,417 answerable dev questions, each with 17 to 20 paragraphs) as the
hand-built Benchmark `musique-ans`: Cases from a sha256-checked mirror of the official dev file,
one Candidate call per Case, and the paper's own scorer copied verbatim. Answer F1 is the
headline; exact match and support F1 ride beside it as Named Scores. No Judge.

Spec: `docs/spec/2026-10-07-OME-1475-musique-ans.md` · Plan: `docs/plan/2026-10-07-OME-1475-musique-ans.md`

Ledgers: `docs/work/2026-10-06-ome-1475-musique-spec.md` (PR 1); PRs 2–4 add their own.
