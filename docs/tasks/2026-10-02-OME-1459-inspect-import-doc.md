---
id: OME-1459
linear_url: https://linear.app/openmined/issue/OME-1459/document-what-we-take-from-an-inspect-eval-and-which-screamingface
status: done
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous, task]
parent: OME-1299
created: 2026-10-02
closed: 2026-10-02
---

# Document what we take from an inspect eval and which ScreamingFace component runs each step

One architecture page, `apps/screamingface-engine/docs/importing-an-inspect-eval.md`, answers
for every field of an inspect `Task` whether we take it, read it as a gate, or replace it with
our own rule, and for every step of inspect's `eval()` which ScreamingFace component does it
instead and when. Every inspect claim links a line at inspect_ai `0.3.263` or inspect_evals
`v0.20.0`; every Engine claim names the symbol and line on `main`. The how-to and the OME-1113
and OME-1273 specs link to it from their first screen. No code changes; `CONTEXT.md` gains no
term.

- 2026-10-02: ticket filed by the owner before work; PR opened from branch
  `OME-1459-inspect-import-doc`, ledger `docs/work/2026-10-02-ome-1459-inspect-import-doc.md`.
