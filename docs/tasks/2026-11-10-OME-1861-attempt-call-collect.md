---
id: OME-1861
linear_url: https://linear.app/openmined/issue/OME-1861/let-a-failed-candidate-call-fail-only-its-own-attempt-not-the-whole
status: done
type: fix
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-10
closed: 2026-11-10
---

# Let a failed Candidate call fail only its own Attempt, not the whole Case

A Benchmark with Attempts asks each Case N times. One Attempt's Candidate call erroring (token
budget spent before any text, a reasoning-only reply, a provider or gateway error) used to raise
out of the whole Case, so the Attempts that answered were lost and the Case scored 0; under the
mean fold 4 right + 1 token cap scored 0.0 where inspect scores 0.8. Each Attempt now runs
inside its own collecting iterate, the errored call becomes that Attempt's failed row by the
error's code, and the fold decides: an empty answer is a wrong try, any other error is no try.

- Spec: `docs/spec/2026-11-10-attempt-call-collect.md`
- Plan: `docs/plan/2026-11-10-attempt-call-collect.md`
- Ledger: `docs/work/2026-11-10-attempt-call-collect.md`
- Stacked on OME-1856 (its PR first), blocks OME-1855's ZeroBench import.
