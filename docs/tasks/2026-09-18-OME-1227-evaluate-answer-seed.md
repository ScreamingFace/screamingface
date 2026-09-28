---
id: OME-1227
linear_url: https://linear.app/openmined/issue/OME-1227/accept-a-seed-on-sfevaluate-so-a-notebook-can-ask-for-a-reproducible
status: in_progress
type: task
priority: P2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-18
closed:
---

# Accept a seed on sf.evaluate so a notebook can ask for a reproducible run

Answer seeds work on `Client.evaluate` but the module-level `sf.evaluate` — the call every
`examples/*.ipynb` uses — omits the keyword, so `sf.evaluate(..., answer_seed=42)` raises
`TypeError`. Mirror the Client's signature in the wrapper and forward on both branches.

Public-surface change: `public_surface_snapshot.json` moves, so it needs the owner's
`--skip-append-only` run.

Ledger: `docs/work/2026-09-18-OME-1227-evaluate-answer-seed.md`
