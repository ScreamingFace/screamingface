# B4 — /anthropic/claude-haiku-4-5?q=('hi')!'go'

Measured 2026-09-27T02:29:46.304305+00:00 on the kind environment (report only, ans:Q3).
PROD SHAPE: workerSlots=4, warmChildren=2 per pod, 2 pods (as dev/staging/prod), AFTER F6 and F8-F11; n=100 per phase. Same target and stub (200 ms) as B1 and the 2026-09-26 B4.

| Phase | n | p50 ms | p95 ms | p99 ms | max ms | errors |
|---|---|---|---|---|---|---|
| sequential | 100 | 350.1 | 1631.7 | 1761.1 | 1761.1 | 0 |
| concurrency 8 | 100 | 4822.2 | 6076.8 | 6531.0 | 6531.0 | 0 |

Errors by kind: `{"sequential": {}, "concurrency_8": {}}`

Worker histograms:
- `screamingface_engine_worker_handoff_latency_s`: {'count': 101.0, 'sum': 104.56916179198743, 'mean_s': 1.0353}
- `screamingface_engine_worker_child_boot_s`: {'count': 101.0, 'sum': 208.9106084149971, 'mean_s': 2.0684}
