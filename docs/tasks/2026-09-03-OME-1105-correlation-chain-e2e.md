---
id: OME-1105
linear_url: https://linear.app/openmined/issue/OME-1105/add-the-correlation-chain-ladder-to-the-local-e2e-harness
status: in_progress
type: null
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-03
closed:
---

# Add the correlation-chain ladder to the local e2e harness

Makes the tracing roadmap's rungs testable **without cluster access** — the live-k8s notebook
(`OME-1074`) needs credentials behind a break-glass tool, while the local harness needs only
Docker and already boots the real engine + real aigateway.

`tests/e2e/test_correlation_chain.py` holds five rungs, every one `xfail(strict=True)`. Strict
is the mechanism: a rung that starts passing FAILS the suite, so the change implementing it
must delete its marker in the same PR.

Observed running: **5 xfailed, 0 failed**.

**The finding.** Rung 1 was planned to pass — `OME-967` is merged — and cannot. From the
public SDK surface there is no way to read a completed run's trace id: it reaches only the
error hierarchy, `Report` has no trace field, and a board run does not raise because DRACO
collects case errors into rows. The user with bad results rather than an exception, who most
needs to quote an id, cannot get one. Closing rung 1 means giving `Report` a trace id.

Ledger: `docs/work/2026-09-03-OME-1105-correlation-chain-e2e.md`.
