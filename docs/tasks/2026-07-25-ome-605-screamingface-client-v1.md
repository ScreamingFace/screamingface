---
id: OME-605
linear_url: https://linear.app/openmined/issue/OME-605/implement-the-screamingface-python-client-v1
status: in_progress
type: feature
priority: high
labels: [py-screamingface, agentic, autonomous]
created: 2026-07-25
closed:
---

Implement the greenfield v1 interface for the `screamingface` Python package around one complete
evaluation operation:

```python
client = sf.Client()
report = client.evaluate(candidates, benchmark="draco", limit=5)
```

The work is limited to `packages/screamingface`. It covers the synchronous and asynchronous
Clients, Client-independent Recipe values, internal URL4 compilation, event consumption, strict
Engine result/Event decoding, immutable Report assembly, documentation, tests, and the quickstart.

It does not change URL4, AI Gateway, `url4-cloud`, Studio, or the separately owned ScreamingFace
Engine implementation. Custom Benchmark publication, public execution stages, Artifact retrieval,
leaderboard submission, and explicit resume/cancellation interfaces are outside v1 scope.

Implementation begins only after the consolidated specification and plan are approved. At that
point, the Linear `who-acts` label changes from `design-session` to `autonomous`.
