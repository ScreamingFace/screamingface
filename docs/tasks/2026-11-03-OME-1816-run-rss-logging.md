---
id: OME-1816
linear_url: https://linear.app/openmined/issue/OME-1816/engine-logs-each-runs-own-rss-current-and-peak-at-run-start-cases-load
status: in_review
type: improvement
priority: none
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-03
---

# Engine logs each run's own RSS (current and peak) at run start, Cases load and run end

The engine logs the run process's own memory (current RSS from `/proc/self/statm`, peak RSS from
`getrusage`, in MiB, standard library only) at `run_start`, at `cases_loaded` on both Cases routes, and
at `run_end` (including failed runs). It is evidence for the FigQA memory investigation on fusion.dev.

Ledger: `docs/work/2026-10-31-run-rss-logging.md`.
