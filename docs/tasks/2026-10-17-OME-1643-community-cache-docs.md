# OME-1643 — Document the community-cache pull and use_cache= on docs.screamingface.ai

Status: In Review
Labels: repo-dev-processes, agentic, autonomous
Parent: OME-1311
Blocked by: OME-1639
Linear: https://linear.app/openmined/issue/OME-1643

Public-docs half of epic OME-1311 (PR 4 of 4), stacked on OME-1639, OME-1635 and OME-1631. The
caching page no longer says a local engine cannot get the community's hits: it documents the
community-cache pull (`sf.cache.pull_from_remote` / `screamingface cache pull`) and
`use_cache=False`. The module, Client, evaluation, error and installation pages gain `sf.cache`,
`use_cache` and `CachePullError`. Spec decisions 9 and 11 are updated to the reviewed behaviour.
Draft PR.

Ledger: ../work/2026-10-17-community-cache-docs.md
Spec: ../spec/2026-10-15-community-cache.md
Plan: ../plan/2026-10-15-community-cache.md
