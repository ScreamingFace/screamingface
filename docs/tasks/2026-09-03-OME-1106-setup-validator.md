---
id: OME-1106
linear_url: https://linear.app/openmined/issue/OME-1106/add-a-setup-validator-for-the-traceability-e2e-lanes
status: in_progress
type: task
priority: 3
labels: [repo, agentic, autonomous, task]
created: 2026-09-03
closed:
---

# Add a setup validator for the traceability e2e lanes

`e2e/failor/check_setup.py` reports, per lane, whether this machine can run the traceability
rungs — with the exact remedy for anything missing. Every prerequisite it checks was found
the hard way during `OME-1105`.

The dangerous one it guards: without prepared draco assets **every rung skips and `pytest`
exits 0**, so an all-skipped run is indistinguishable from a passing one by exit code. The
validator says so in as many words.

Read-only and offline: it never SSHes, authenticates, or contacts a cluster. The firecall
bastion (`firecall@172.190.209.255` → AKS `aks-dev-eastus`, namespaces `sf-aigw`,
`sf-fusion`, `sf-scoreboard`) is recorded as constants and reported UNKNOWN rather than
probed — opening a session to a jump host belongs to the operator.

Only the local lane decides the exit code; the k8s lane depends on credentials nobody here
controls, and a permanently red validator is an ignored one.

Ledger: `docs/work/2026-09-03-OME-1106-setup-validator.md`.
