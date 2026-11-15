---
id: OME-1856
linear_url: https://linear.app/openmined/issue/OME-1856/let-a-benchmark-score-a-case-as-the-mean-of-its-attempts-as-inspects
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-09
closed: 2026-11-09
---

# Let a Benchmark score a Case as the mean of its Attempts, as inspect's pass@1 does

A Task whose first declared reducer is inspect's own `pass_at(1)` over N epochs imports as N
Attempts folded by the mean (the share of Attempts at full marks, c/N), the rule ZeroBench's
five-sample pass@1 needs; the marking room folds by it, the tally replays inspect's reducer and
checks the two agree, and the card says "mean over N Attempts". Any-of-N rows and one-Attempt
rows are byte-identical. Amends OME-1458's D2 and D4.

Spec: `docs/spec/2026-11-09-attempts-mean-fold.md`. Ledger: `docs/work/2026-11-09-attempts-mean-fold.md`.
