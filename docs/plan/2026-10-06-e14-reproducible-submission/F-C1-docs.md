# F-C1 — docs: reproducibility through a frozen copy (rework of C1)

- **Worktree:** `.claude/worktrees/e14-c1-docs` · **Branch:** `e14-c1-docs` (rework in place, new commits) ·
  **Base:** `e14-b5-sdk-reproduce`
- **Design:** `02-frozen-copy-design.md` (binding). Read the FINAL code in this checkout for exact names.

## Changes

- Replace the cache-revision story everywhere C1 wrote it (`public-docs` caching page "Reproducing a
  submission", leaderboards guide and API pages, `CandidateResultPage.vue`, the url4 guide, the learn
  leaderboard page, `CONTEXT.md`):
  - `sf.evaluate(..., capture=True)` makes a frozen copy of the run: every model answer and every web-tool
    result, kept forever; best effort, so a run can be `partial`.
  - `capture_status` complete/partial and why (a refused or failed capture, a streaming call, a failed open or
    seal, an older gateway).
  - `sf.reproduce(score)`: runs the stored url4 and seed against the frozen copy; no provider, no Tavily, $0;
    works after a model is retired; the outcome table and the reasons `frozen_copy_miss`,
    `frozen_copy_unavailable`, `replay_unsupported`, `run_failed`, `benchmark_revision_changed`,
    `score_differs`, `partial`, `unknown`.
  - Remove every mention of cache revisions, `only-if-cached`, `reproducible`, `cache_revision`.
- Glossary (`CONTEXT.md`): replace Cache Revision / Reproducible with **Frozen Copy** and **Capture Status**;
  keep **Reproduction** (a replay against a frozen copy). Same entry style; lines ≤ 100 chars.
- Do not document gateway-internal routes or headers on client pages.

## Verify

`public-docs`: `npm ci`, `npm run build`, `npm run lint` (report the result lines).
