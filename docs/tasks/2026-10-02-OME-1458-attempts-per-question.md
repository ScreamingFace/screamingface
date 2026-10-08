---
id: OME-1458
linear_url: https://linear.app/openmined/issue/OME-1458/decide-how-a-benchmark-that-allows-several-attempts-per-question-is
status: in_progress
type: decision
priority: medium
labels: [screamingface-engine, human, design-session, decision]
parent: OME-1299
created: 2026-10-02
closed:
---

# Decide how a benchmark that allows several attempts per question is scored

Some Benchmarks give the model more than one Attempt per question and count the question right if
any Attempt is right (ARC-AGI-2: two Attempts per test grid; ZeroBench: pass@5). Our spine asks
each Case once, so such a Benchmark cannot be reproduced, and the inspect importer silently runs a
Task's `epochs` at one.

Decision (2026-10-07, spec `docs/spec/2026-10-07-OME-1458-attempts-per-case.md`): a Benchmark
declares `attempts=N`; each Case is asked N times, each Attempt graded on its own, and a Check is
met if any Attempt met it. Delivered as this docs PR plus an importer refusal of `epochs` > 1
(PR 2 of 6); the build is PRs 3 to 6 on this ticket (SDK, AI gateway, Engine, importer mapping).
