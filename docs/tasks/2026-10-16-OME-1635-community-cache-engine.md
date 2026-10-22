# OME-1635 — Proxy the community-cache pages through the Engine

Status: In Review
Labels: screamingface-engine, agentic, autonomous
Parent: OME-1311
Blocked by: OME-1631
Linear: https://linear.app/openmined/issue/OME-1635

Engine half of epic OME-1311 (PR 2 of 3), stacked on OME-1631 (#1433). `GET /v1/cache/entries`
on the hosted Engine forwards the caller's verified identity, trace context and the four query
parameters to the gateway's route of the same path and streams the NDJSON page back as it
arrives, gzip passed through still compressed, so the Engine never decodes or holds a page.
503 without a gateway address; gateway failures map to problem+json. Wired into the hosted App
only. Draft PR; `sf.cache.pull_from_remote` (PR 3) follows under the epic.

Ledger: ../work/2026-10-16-community-cache-engine.md
Spec: ../spec/2026-10-15-community-cache.md
Plan: ../plan/2026-10-15-community-cache.md
