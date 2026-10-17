# OME-1596 plan — author and paper metadata, pinned cache lookup, Reproduce button

**Spec:** `docs/spec/2026-10-13-OME-1596-reproducible-row-mark.md` (approved 2026-10-15)
**Status:** approved by the owner piece by piece, 2026-10-15 · **Stack:** scoreboard

## Delivery (owner, 2026-10-15)

One PR on `OME-1596-reproducible-row-mark`, several commits, each tested first (RED) and green on
`uv run .claude/scripts/run_gates.py scoreboard` before the next.

| # | Commit | Contents |
|---|---|---|
| 1 | docs | spec, ledger, mirror (done: `f11d8368`, `7e2319db`) and this plan |
| 2 | storage | migration `0021`: `scores.authors_metadata`, `scores.paper_metadata` (nullable JSON); `score_metadata_events.{old,new}_{authors,paper}_metadata` (nullable JSON); unique index on `scores.frozen_copy_id` (nulls allowed). Model fields. Guard in the migration (below). |
| 3 | metadata | shared validator (spec §3); `ScoreSubmission`, `ScoreMetadataPatch` and read schemas; `paper_metadata.url` ↔ `paper_url`; public masking serializer reusing `_publish_authors`'s naming; export exclusion when null; submit, PATCH and same-owner resubmit (replace whole object, `null` clears, removing an author drops their entry); edit-log events. |
| 4 | lookup | `GET /v1/scores/by-pinned-cache/{frozen_copy_id}` (spec §5); identical 404 for unknown, malformed and private; 422 `frozen_copy_claimed` on a second claim, mapped from the unique-index violation and pre-checked for a clear message. |
| 5 | rows and portal | `RankedLeaderboardEntry.pinned_cache` (complete-capture public rows); Reproduce button in `benchmark.js` behind `SHOW_REPRODUCE_BUTTON = false`; `renderReproduced` removed from `spec.js`. |

## Duplicate copy ids (owner, 2026-10-15, option A)

1. **Before merge:** a read-only query on dev and production through a `/pulse firecall` session:
   `SELECT frozen_copy_id, count(*) FROM scores WHERE frozen_copy_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1;`
   Any row stops the rollout for an owner decision.
2. **At deploy:** migration `0021` runs the same check before creating the index and, if it finds
   duplicates, fails with a message naming the copy ids and their score ids instead of a raw database
   error.

## Tests per commit

Spec §7, split by commit. Owner rules: structured checks only (parsed JSON or HTML, model fields), no
regular expressions or substring searches; no prior test edited without owner approval; new Node test
files are listed by name in `scoreboard-tests.yml` and the `.claude/sdlc.local.md` gate line; portal
files carry no ticket ids or `FEATURE:`/`INVARIANT` anchors (`test_every_served_asset_…`).

## Rollout

1. Duplicate check on dev and production (above).
2. Merge; dev deploys; verify on dev (submit with metadata, read masked, lookup, no button).
3. Production deploy, switch off.
4. SDK release with `evaluate(pinned_cache=…)` (`OME-1613`), then a one-line PR turns the switch on.
5. Docs (`OME-1614`) with or after the SDK release.
