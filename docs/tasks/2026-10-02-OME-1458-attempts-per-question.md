---
id: OME-1458
linear_url: https://linear.app/openmined/issue/OME-1458/let-a-benchmark-ask-each-question-several-times-and-count-it-right-if
status: done
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-10-02
closed: 2026-10-08
---

# Let a benchmark ask each question several times and count it right if any answer is right

Some Benchmarks give the model more than one Attempt per question and count the question right if
any Attempt is right (ARC-AGI-2: two Attempts per test grid; ZeroBench: pass@5). Our spine asked
each Case once, so such a Benchmark could not be reproduced, and the inspect importer silently ran a
Task's `epochs` at one.

Decision (2026-10-07, spec `docs/spec/2026-10-07-OME-1458-attempts-per-case.md`): a Benchmark
declares `attempts=N`; each Case is asked N times, each Attempt graded on its own, and a Check is
met if any Attempt met it. Delivered as seven PRs on this ticket (plan
`docs/plan/2026-10-08-OME-1458-attempts-per-case.md`): the spec and plan, the importer refusal,
the SDK, the AI gateway, the Engine egress, the Engine loop and fold, and the importer mapping
(this one, which closes the ticket). Deploy order: SDK release, then gateway, then Engine.
