---
id: OME-1714
linear_url: https://linear.app/openmined/issue/OME-1714/remove-wmdp-benchmark-leaderboards-from-the-sf-catalog
status: done
type: improvement
priority: urgent
labels: [screamingface-engine, improvement-idea]
parent: none (product-filed)
created: 2026-10-22
closed: 2026-10-22
---

# Remove WMDP-* benchmark leaderboards from the SF catalog

Product asked for WMDP-Bio, WMDP-Chem and WMDP-Cyber to come off the public catalogue: listed,
they read as an invitation to optimise Fusions for hazardous-knowledge elicitation. The owner
chose to unlist, not delete (2026-10-22).

- New **Unlisted Benchmark** mark on the Engine's Benchmark definition: absent from
  `GET /v1/benchmarks`, still served by `GET /v1/benchmarks/{id}`, never on the wire, never in
  the revision. The three WMDP rows carry it.
- SDK notebook 12 no longer names the three ids.
- The Scoreboard rows (0 Scores, 0 baselines) are an operator step with the existing retire tool,
  after the Engine deploy, on prod and dev.

Ledger: `docs/work/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md`.
Spec: `docs/spec/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md`.
Plan: `docs/plan/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md`.
