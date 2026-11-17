---
id: OME-1811
linear_url: https://linear.app/openmined/issue/OME-1811
status: done
type: task
priority: medium
labels: [screamingface-engine, agentic]
parent: OME-1529
created: 2026-11-03
closed: 2026-11-17
---

# Refuse url4:// remote-node calls in engine runs with x.remote_node_unsupported

Engine runs call `url4.dag.run` directly, so they never applied url4's remote-node refusal. A
`url4://` call reached the world node's outbound layer, and only the empty peer allowlist stopped it,
with the wrong code. Both run calls in `runner/executor.py` now apply the refusal through a new
public url4 hook, `url4.dag.refuse_remote_nodes`.

- 2026-11-03: built on the image stack; ratchet change approved by the owner.
- 2026-11-11: moved onto main (it does not need the stack); PR opened.
- Ledger: `docs/work/2026-11-03-engine-remote-node-refusal.md`
- 2026-11-17: #1750 merged as 455166b0d. Done.
