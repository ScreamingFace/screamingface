---
id: OME-1827
linear_url: https://linear.app/openmined/issue/OME-1827/catch-the-worker-loading-the-database-stack-one-import-away-and-close
status: in_progress
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-11-05
closed:
---

# Catch the worker loading the database stack one import away, and close E1's records (E5 P1 review follow-ups)

A review comment on #1627 arrived after it merged. This unit adds a real-import guard so the
worker cannot load the Run registry or the database stack through a control-plane module, and
closes E1's ledger and the `OME-1797` mirror.

Ledger: `docs/work/2026-11-05-e5-p1-review-followups.md`.
