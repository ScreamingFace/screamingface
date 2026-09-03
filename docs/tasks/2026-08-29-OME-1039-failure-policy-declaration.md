---
id: OME-1039
linear_url: https://linear.app/openmined/issue/OME-1039/declare-each-benchmarks-failure-policy-and-interaction-type-as-visible
status: in_progress
type:
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-08-29
closed:
---

# Declare each benchmark's failure policy and interaction type as visible parameters when the spine takes over grading

First code PR of the OME-1024 spine chain. Every Benchmark now registers a required,
typed declaration record (`failure_policy` + `interaction`, no defaults, named errors on
unknown values), surfaced in the catalog and resource manifests — so the scoring policy
is approvable from the manifest, never a hidden spine default. Also extracts the
five-rung failure ladder duplicated between `gdpval/aggregate.py` and
`healthbench/aggregate.py` into the new `benchmarks/spine/case_ladder.py` — the first
spine module. Failure codes and message texts stay byte-identical per board.

Implementation finding: all four boards route through the shared
`finalize_candidate_result`, which is uniform coverage-declare behavior — so all six
builtins declare `coverage-declare`; `withhold` is a valid enum value with no current
claimant (Linear comment 2026-09-03).

Ledger: `docs/work/2026-09-03-OME-1039-failure-policy-declaration.md`
