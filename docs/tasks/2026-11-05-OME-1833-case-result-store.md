---
id: OME-1833
linear_url: https://linear.app/openmined/issue/OME-1833/stream-case-results-as-ndjson-so-a-full-benchmark-run-stays-within-its
status: done
type: improvement
priority: none
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-05
closed: 2026-11-07
---

# Stream Case results as NDJSON so a full benchmark run stays within its memory budget

Each Case's result goes to a run-scoped NDJSON store as it finishes, and the aggregate streams it
back. On the full 12,032-Case MMLU-Pro run, per-Case growth drops from 12.9 to 0.4 KiB and the peak
from 2,963 to 1,016 MiB. The report shape is unchanged.

Spec: `docs/spec/2026-11-05-case-result-store.md`. Plan: `docs/plan/2026-11-05-case-result-store.md`. Ledger: `docs/work/2026-11-05-case-result-store.md`.
