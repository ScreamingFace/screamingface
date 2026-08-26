---
id: OME-998
linear_url: https://linear.app/openmined/issue/OME-998/connect-to-the-running-local-stack-by-default-instead-of-the-hosted
status: backlog
type: null
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-26
closed: null
---

# Connect to the running local stack by default instead of the hosted engine

`sf.connect()` points at the hosted engine even while `screamingface up`'s local stack is
running, so every local tester's first notebook run stalls at "waiting / Authorize" unless
they already know to export `SCREAMINGFACE_ENGINE_URL`.

Proposed precedence in the SDK's default client: explicit env var → a running (liveness-checked)
local runtime discovered from the state `screamingface up` writes → hosted default. Full
Before/After and the don't-regress list live in the Linear issue.

Surfaced while testing PR #714's GDPval notebook (OME-971); not that board's defect.
