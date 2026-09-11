---
id: OME-1097
linear_url: https://linear.app/openmined/issue/OME-1097/share-the-scored-path-and-scorer-for-rubric-benchmarks-behind-a-grade
status: done
type:
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-07
closed: 2026-09-09
---

# Share the scored path and scorer for rubric benchmarks behind a `grade_case` hook

Third code PR of the OME-1024 spine chain. The scored path (mark one case against the
rubric, fold marks into the exam result) exists near byte-identically in
`gdpval/aggregate.py` and `healthbench/aggregate.py`. It moves into `benchmarks/spine/`
behind one per-board async hook, `grade_case` — the epic's public seam, constrained by
three consumers (enclave judge, inspect_evals scorer shim, future agentic boards): plain
serializable data in, complete grade out, payloads kind-tagged never bare `str`. The
exam scorer becomes a parameter (the board's mean); both `aggregate.py` files are
deleted and each board keeps a hook module under ~150 lines.

Guard: healthbench-worst30 golden on every rung; gdpval-text has no golden yet
(OME-1098) — its half runs on unit tests plus a metric-key byte-identity pin.

Ledger: `docs/work/2026-09-07-OME-1097-shared-scored-path.md`
