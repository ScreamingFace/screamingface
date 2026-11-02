# OME-1639 — Pull the community cache into a local engine: sf.cache.pull_from_remote and use_cache=

Status: In Review
Labels: client-sf, agentic, autonomous
Parent: OME-1311
Blocked by: OME-1635
Linear: https://linear.app/openmined/issue/OME-1639

SDK half of epic OME-1311 (PR 3 of 4), stacked on OME-1635 (Engine proxy) and OME-1631 (gateway
route). `sf.cache.pull_from_remote()` and `screamingface cache pull` copy the hosted community
cache into the local gateway database through the hosted Engine (production unless `url=` says
otherwise), with progress, retries and an in-memory resume. `evaluate(..., use_cache=False)` opts
one evaluation out of the request cache, and `screamingface up` now caches by default. Draft PR;
the public docs follow as PR 4.

Ledger: ../work/2026-10-16-community-cache-sdk.md
Spec: ../spec/2026-10-15-community-cache.md
Plan: ../plan/2026-10-15-community-cache.md
