---
title: Search metadata on the home, about, spec and data pages — plan
status: proposed
created: 2026-11-13
spec: docs/spec/2026-11-13-portal-page-metadata-spec.md
---

# Search metadata on the home, about, spec and data pages — plan

1. `portal/index.html`
   - Title: `AI leaderboard for fusions, ensembles & routers | ScreamingFace`.
   - Description: `Compare leaderboard scores and costs for models and fusions: ensembles, routers and cascades. Copy available recipes to rerun submitted results.`
   - The same text in `og:title`, `twitter:title`, `og:description`, `twitter:description`.
   - `<link rel="canonical" href="https://leaderboard.screamingface.ai/">`.
2. `portal/about.html`: `<link rel="canonical" href="https://leaderboard.screamingface.ai/about.html">`.
3. `portal/spec.html`, `portal/data.html`: retain existing indexing; remove the proposed blanket `noindex` additions.
4. Tests in a new file, `tests/unit/test_portal_page_metadata.py`, reading the served pages.

## Review-fix implementation, 2026-11-17

1. Integrate current main while preserving original PR history.
2. Add failing regression coverage for: Parsed title/description/canonical agreement, bare and parameterized spec/data indexing, independent full scoreboard gates and combined browser compatibility with PR 1800.
3. Implement the accepted scope and update the obsolete test contracts.
4. Run full scoreboard and repository gates; inspect desktop/mobile in both themes.
5. Update the existing PR as FilipBolt.
