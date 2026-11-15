---
id: OME-1872
linear_url: https://linear.app/openmined/issue/OME-1872/retry-a-candidate-model-call-when-the-gateway-fails-for-a-moment
status: done
type: fix
priority: medium
labels: [screamingface-engine, agentic, design-session]
parent: OME-1299
created: 2026-11-11
closed: 2026-11-11
---

# Retry a Candidate model call when the gateway fails for a moment

A Candidate model call the AI gateway answered with 429 or 5xx was marked temporary, but nothing
asked it again, so the Case failed on one bad minute at the gateway. The Engine's connector now
waits (about 10 s, then about 30 s, longer when the gateway's `Retry-After` asks) and asks a
Candidate call again, 2 times, before the failure stands. Judges keep their own 2 re-asks, and a
replay never retries.

- Ledger: `docs/work/2026-11-11-candidate-call-retry.md`
