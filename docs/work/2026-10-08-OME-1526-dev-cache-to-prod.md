---
ticket: OME-1526
stack: repo
status: done
started: 2026-10-08
finished: 2026-10-08
---

# OME-1526 — migrate every live dev response-cache row to production

## Intent

Copy dev's whole `request_cache_entries` table to prod, so reruns of anything already run on dev are free on prod and score the same. In OME-1501, copying only the rows one run touched was not enough: a second run of the same recipe requested 41 keys the first never touched.

## Planned changes

No code. An operational data copy through the existing admin snapshot upload (OME-951). The export scripts and archives stay on the owner's machine (`~/draco-rerun/prod_migration_all/`), in line with the decision to keep `snapshot-cache` untracked.

## Test plan

- Reconcile key by key: the two earlier uploaded archives plus the new one must cover every dev key with identical content.
- Read the new archive with aigateway's own `snapshot.py` reader, check its sha256 against the manifest, and check the manifest's revisions against `active_cache_revisions()`.
- After the load, run cached reruns on prod and expect 0 misses, $0 and dev's exact scores.

## Acceptance

- Prod holds every dev row. Cached reruns of published dev recipes have 0 misses.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** none in the repo; this mirror and ledger only.
- **Commits:** this docs PR.
- **Gates:**
  - Dev inventory: 467,895 rows, all openrouter; `expires_at` NULL on every row; no revision recorded in `metadata_json`.
  - Archive: `cache_part1.sql.gz`, 224,087 rows, 60.5 MB gzip. 243,808 rows were already on prod with identical content and were left out. The gateway reader read every row; the sha256 and revisions matched.
  - Reconciliation: 467,895 / 467,895 dev keys covered. 0 missing, 0 with different content, 0 duplicates, 0 extra.
  - Load (2026-10-08 09:54, merge): 224,087 staged · 224,075 inserted · 12 replaced. Prod went from 246,924 to 470,999 rows.
  - Prod cached reruns: draco-3pass `fable_plus_gpt` 0.6862, `pareto_lean` 0.5456, `claude-fable-5` 0.5322, and ifeval `best_open_source` (1 case) 1.0. All had 0 misses, cost $0, and match dev exactly.
- **Deviations:**
  - The planned per-revision split was impossible, because no row records its revision. All rows were taken, per the owner's scope.
  - There were no Tavily rows.
  - Prod's published draco-3pass rows for the 3 recipes still show their pre-migration scores (0.6869, 0.5440, 0.5346). Republishing needs a prod firecall deletion; the owner chose to keep them for now.
  - The ifeval cache rows are unpriced.
