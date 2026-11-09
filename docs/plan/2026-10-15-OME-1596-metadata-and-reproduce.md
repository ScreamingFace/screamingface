# OME-1596 plan — author and paper metadata, pinned cache lookup, Reproduce button

**Spec:** `docs/spec/2026-10-13-OME-1596-reproducible-row-mark.md` (approved 2026-10-15)
**Status:** approved by the owner piece by piece, 2026-10-15 · **Stack:** scoreboard

## Delivery (owner, 2026-10-15)

One PR on `OME-1596-reproducible-row-mark`, several commits, each tested first (RED) and green on
`uv run .claude/scripts/run_gates.py scoreboard` before the next.

| # | Commit | Contents |
|---|---|---|
| 1 | docs | spec, ledger, mirror (done: `docs(scoreboard): spec author and paper metadata and the Reproduce button`, `docs(scoreboard): make the Reproduce switch a portal constant`) and this plan |
| 2 | storage | migration `0021`: `scores.authors_metadata`, `scores.paper_metadata` (nullable JSON); `score_metadata_events.{old,new}_{authors,paper}_metadata` (nullable JSON); unique index on `scores.frozen_copy_id` (nulls allowed). Model fields. Guard in the migration (below). |
| 3 | metadata | shared validator (spec §3); `ScoreSubmission`, `ScoreMetadataPatch` and read schemas; `paper_metadata.url` ↔ `paper_url`; public masking serializer reusing `_publish_authors`'s naming; export exclusion when null; sent objects replace whole objects; omission preserves on both write paths; `null` preserves on same-owner resubmit but clears on PATCH (owner decision 2026-10-19, spec §2); removing an author drops their entry; edit-log events. |
| 4 | lookup | `GET /v1/public/scores/by-pinned-cache/{frozen_copy_id}` (spec §5); identical 404 for unknown, malformed and private; 422 `frozen_copy_claimed` on a second claim, mapped from the unique-index violation and pre-checked for a clear message. |
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

Review follow-up (2026-10-19): add RED regressions for malformed author-metadata email keys on
submit, resubmit and PATCH, then reuse the existing AuthorEmail type in the shared validator.
Add a new portal test file for accessible Copy/Reproduce success/failure and repeat feedback;
register it in both gate lists, then fix the shared helper without changing button styling or
enabling Reproduce. Run the complete Scoreboard gates.

Owner decision (2026-10-19, after that follow-up): retain the implemented resubmit-null behavior
and align the contract, superseding row 3's earlier blanket "null clears" wording. Null and omission
preserve each metadata object on same-owner resubmission; PATCH null clears, PATCH omission
preserves. Update spec §2/§7, submission OpenAPI descriptions and the task mirror, and append the
decision to the ledger. Add an explicit-null resubmission characterization test; retain the existing
omission and PATCH-clear tests. No runtime change, no test rewrite and no migration.

Privacy-race follow-up (2026-10-19): write deterministic interleaving regressions before adding
the route-level final `turned_private` check to the pinned-cache lookup. Keep both reads inside
the OperationalError boundary; compare the refusal body and cache policy with private/unknown
lookups, and test failure of the final read. Correct stale comments without changing the shared
visibility helper, models or migration. Run the focused tests and full Scoreboard/repo gates.

1. Duplicate check on dev and production (above).
2. Merge; dev deploys; verify on dev (submit with metadata, read masked, lookup, no button).
3. Production deploy, switch off.
4. SDK release with `evaluate(pinned_cache=…)` (`OME-1613`), then `OME-1655` turns the switch on
   (its own ticket since 2026-10-19; this ticket ships the button behind the switch, off).
5. Docs (`OME-1614`) with or after the SDK release.
