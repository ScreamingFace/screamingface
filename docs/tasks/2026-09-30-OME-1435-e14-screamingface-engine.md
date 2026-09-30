---
id: OME-1435
linear_url: https://linear.app/openmined/issue/OME-1435
status: in_progress
type: feature
priority: 2
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1307
created: 2026-09-30
closed:
---

# Carry E14 freeze and replay grants through the Engine

E14 in `apps/screamingface-engine`: run plumbing for cache versions.

- **Freeze proxy (ENG-freeze):** `POST /v1/cache-versions` sends the request to the gateway with the caller identity.
- **Replay carry (ENG-replay):** the grant rides the start request. The engine never decodes the grant. The connector writes the gateway header last and counts version hits, misses and repeated-key collapses into the C12 frame.
- **Final-check fix RP-X1:** a failed grant call that got a response counts as a miss. A transport failure does not count (Q26).

Tests: SC-21 and RP-11..RP-15. The gates are green, including check_layering.

Spec: `docs/spec/2026-09-29-e14-reproducible-submission/`. Plans: `docs/plan/2026-09-29-e14-reproducible-submission/` (decisions D1-D8, Q19-Q30). All E14 units ship in one PR, and each component has its own leaf (CLAUDE.md: one sub-issue for each app or package).
