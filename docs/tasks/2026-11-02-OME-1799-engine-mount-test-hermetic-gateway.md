---
id: OME-1799
linear_url: https://linear.app/openmined/issue/OME-1799/stop-an-engine-test-from-failing-on-laptops-that-run-their-own-gateway
status: done
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
created: 2026-11-02
closed: 2026-11-02
---

# Stop an Engine test from failing on laptops that run their own gateway

The Engine mount test built its local App without naming a gateway, so it reached whatever
gateway ran on the developer's machine at `127.0.0.1:9105`. A gateway listing a local `ollama`
model made the test's sample run build its own world and log the holdings-shelf line twice, so
the pre-push hook refused Engine pushes from that laptop while CI stayed green. The test now
names `http://aigateway.test`, the address its own config file already uses. The edit to the
existing test is approved in `.claude/test-change-approvals/OME-1799.json`.

Ledger: `../work/2026-11-02-engine-mount-test-hermetic-gateway.md`.
