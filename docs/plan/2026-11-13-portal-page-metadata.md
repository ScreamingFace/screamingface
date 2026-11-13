---
title: Search metadata on the home, about, spec and data pages — plan
status: proposed
created: 2026-11-13
spec: docs/spec/2026-11-13-portal-page-metadata-spec.md
---

# Search metadata on the home, about, spec and data pages — plan

1. `portal/index.html`
   - Title: `AI leaderboard for fusions, ensembles & routers | ScreamingFace`.
   - Description: `The leaderboard for fusions. Benchmark scores and cost for single models and
     multi-model systems: ensembles, routers, cascades. Copy any result's recipe and rerun it.`
   - The same text in `og:title`, `twitter:title`, `og:description`, `twitter:description`.
   - `<link rel="canonical" href="https://leaderboard.screamingface.ai/">`.
2. `portal/about.html`: `<link rel="canonical" href="https://leaderboard.screamingface.ai/about.html">`.
3. `portal/spec.html`, `portal/data.html`: `<meta name="robots" content="noindex,follow">`.
4. Tests in a new file, `tests/unit/test_portal_page_metadata.py`, reading the served pages.
