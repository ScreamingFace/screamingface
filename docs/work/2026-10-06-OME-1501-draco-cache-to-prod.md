---
ticket: OME-1501
stack: repo
status: done
started: 2026-10-07
finished: 2026-10-08
---

# OME-1501 — move draco-3pass dev cache to production, then rerun to populate the board

## Intent

Prod's draco-3pass board was empty at launch. Copy the dev response cache that the 7 draco-3pass recipes need to prod, rerun the recipes against prod from that cache, and submit them so the prod board shows all 7 with full reproduction cost.

## Planned changes

No code. An operational data copy through the admin snapshot upload (OME-951), then reruns and submits through the ScreamingFace client. Export scripts, archives and key lists stay on the owner's machine (`~/draco-rerun/prod_migration*/`).

## Test plan

- One-case probe against prod before the full rerun: expect 160/160 cache hits and $0 spend, as on dev.
- Each rerun passes coverage 1.0 and submits as `complete`.
- Prod board lists all 7 recipes on the current benchmark revision.

## Acceptance

- Prod's draco-3pass board shows all 7 recipes with full reproduction cost.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** none in the repo; this mirror and ledger only.
- **Commits:** this docs PR.
- **Gates:**
  - Load 1 (2026-10-07 13:34, merge): OME-1469 remeasure snapshots, 1,551 rows. Probe missed 160/160 ($3.39 live spend). The rows covered only the unpriced subset.
  - Load 2 (2026-10-07 21:14, merge): run footprint, 83,276 staged · 81,936 inserted · 1,340 replaced. Probe then hit 160/160, $0, $13.01 saved.
  - Load 3 (2026-10-08 01:26, merge): August seed (dev rows created 2026-08-21 and 2026-08-26), 160,532 staged · 160,238 inserted · 294 replaced. Needed because a second run of a recipe requested keys the first never touched. Every later rerun hit 100%.
  - Prod board (read 2026-10-08, revision `2634cec91fd0f19a`), all 7 present:

    | Recipe | Prod | Dev | Submitted (UTC) |
    |---|---|---|---|
    | fable_plus_gpt | 0.6869 | 0.6862 | 2026-10-07 23:51 |
    | opus_plus_gpt | 0.6429 | 0.6421 | 2026-10-08 06:06 |
    | pareto_cross | 0.6192 | 0.6192 | 2026-10-07 23:43 |
    | budget_trio | 0.585 | 0.585 | 2026-10-07 23:47 |
    | best_open_source | 0.5677 | 0.5677 | 2026-10-07 23:39 |
    | pareto_lean | 0.544 | 0.5456 | 2026-10-07 23:40 |
    | claude-fable-5 | 0.5346 | 0.5322 | 2026-10-07 23:31 |

  - Spend: about $25.5 recorded against the owner's $100 cap. Killed parallel runs also spent server-side; that amount is unknown.
- **Deviations:**
  - The ticket planned one scoped export. It took three loads, and the full-table copy followed in OME-1526.
  - Four prod scores differ from dev. Three of those runs made paid live calls before load 3. The cause for opus_plus_gpt was not checked. After OME-1526, cached prod reruns of fable_plus_gpt, pareto_lean and claude-fable-5 match dev exactly. The published rows were kept; replacing them needs a prod firecall deletion.
  - Recipes run in parallel on prod queue on the server, and killing a client does not stop its server-side run. Run them one at a time (about 3.6 min each from cache).
- **Follow-ups (not filed yet):** the SDK builds its Access login link at the host root, but only `/v1/scores` sat behind Access on prod; two runs of one recipe request different judge cache keys.
