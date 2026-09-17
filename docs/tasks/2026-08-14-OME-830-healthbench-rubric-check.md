---
id: OME-830
linear_url: https://linear.app/openmined/issue/OME-830/ship-the-healthbench-check-adapter-and-extract-the-shared-rubric-check
status: In Review
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-14
parent: OME-796
---

# Ship the HealthBench check adapter and extract the shared rubric_check component

Stage 4 of the OME-796 plan as its own PR, stacked on `OME-829-draco-check-adapter`:
the second rubric customer forces out `benchmarks/rubric_check.py` — the shared
marking work (case resolution, rubric reading through a declared shape, one
weight-blind judge pass with exact-request identity and bounded retries, clamped weighted scoring,
sanitized feedback). DRACO migrates onto it with behavior unchanged; HealthBench
lands as a `RubricCheck` declaration only (`healthbench-pass.v1`, threshold 0.5 on
the clamped score, severity feedback), plus its notebook corrective cell.

Acceptance: the deletion test — HealthBench's adapter contains no functions,
classes, or control flow. Unblocks GDPval-rubric / FSResearch as zero-code
check-surface onboardings.

Ledger: `docs/work/2026-08-14-OME-830-healthbench-rubric-check.md`
