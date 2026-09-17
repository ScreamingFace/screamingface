---
id: OME-833
linear_url: https://linear.app/openmined/issue/OME-833/raise-the-local-mode-concurrent-run-ceiling-above-the-client-fan-out
status: In Progress
type: task
priority: Medium
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-14
closed:
---

# Raise the local-mode concurrent run ceiling above the Client fan-out

Local mode refuses Runs with `503 the runner is at capacity — retry shortly` because the
in-process runner ceiling (8) equals the Client's per-Evaluation fan-out (8), leaving no spare
capacity. Abandoned Runs hold a slot for up to 16 hours, because a WebSocket disconnect does
not stop a Run.

Raises `local_max_concurrent_runs` and `DEFAULT_MAX_CONCURRENT_RUNS` to 32, and adds a floor
test that keeps the ceiling above the Client fan-out.

Spec: `docs/spec/2026-08-14-OME-833-local-run-ceiling.md`
Plan: `docs/plan/2026-08-14-OME-833-local-run-ceiling.md`
Ledger: `docs/work/2026-08-14-OME-833-local-run-ceiling.md`
