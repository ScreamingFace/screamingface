---
id: OME-773
linear_url: https://linear.app/openmined/issue/OME-773/promote-the-candidate-result-contract-to-a-pydantic-model-in-the
status: in-progress
type: task
priority: P2
labels: [url4-cloud, agentic, autonomous, task]
created: 2026-08-11
closed:
---

# Promote the candidate-result contract to a pydantic model in the engine

Benchmark aggregates hand-build the `screamingface.candidate-result.v1` dict; the
contract lives only in comments, per-benchmark tests, and the SDK's consumer-side
checks. Two display-truth bugs shipped this way on PR #543 (missing check `outcome`
→ all cases render INCORRECT; missing `pass_rate`/`coverage` → dash tiles).

Replace the dict literals with a pydantic `CandidateResult` model in
`apps/url4-cloud/src/url4_cloud/benchmarks/contract.py`, constructed by every
aggregate, with the invariants as model validators (canonical `{score, pass_rate,
coverage}` trio on scored results; `score None ⇒ metrics {}`; graded checks carry
MET/UNMET `outcome`; per-benchmark metric keys stay open).

Scope here: DRACO + IFEval on branch `ifeval-benchmark` (PR #543). HealthBench
follows on PR #544 (plan in `.dk/plans/2026-08-11-healthbench-canonical-metrics.md`).
SDK keeps its own consumer-side parsing — wire JSON unchanged.
