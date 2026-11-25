---
ticket: OME-1916
stack: scoreboard
status: blocked
started: 2026-11-25
finished:
---

# fusion-leads-landing — Show leaderboards where fusions outperform solo models first

## Intent

OME-1916: on the landing-page benchmark catalogue (`apps/scoreboard/portal/index.html` /
`catalog.js`), list benchmarks where the best fusion score beats the best solo-model score
first, ahead of the rest — alphabetical order (today's only sort) as the tiebreaker within
each group. Decided criterion (ticket body, 2026-11-25): compare the max fusion score vs.
the max solo-model score per benchmark, classified via `classify_candidate_kind`
(OME-1852) — never inferred from `spec_id`/provider count. A benchmark with no fusion
submission or no solo-model submission cannot have a fusion win (resolves false).

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/catalog.py`
  - `BenchmarkSummary` gains `fusion_leads: bool`.
  - `_ranked_candidates()` additionally selects `scores.metadata` (needed to classify each
    ranked candidate's composition type) through both the `ranked` and `candidates` CTEs.
  - `list_benchmark_summaries()`'s main join drops the `candidates.board_rank == 1` filter
    from its `ON` clause (now returns every in-scope ranked candidate per benchmark, not
    just the top one) so the fusion-vs-model comparison is read from the **same statement**
    as `best_score` — `test_summary_uses_two_database_statements` pins the summary endpoint
    at exactly two DB statements total, so this must not add a third query. Rows are
    grouped by benchmark id in Python: the `board_rank == 1` row is still used for
    `best_score` exactly as today; every row in the group is classified via
    `classify_candidate_kind` (unreadable/absent metadata decodes to `"unknown"`, mirroring
    the existing unreadable-`ran_with_providers` handling) and the per-kind max is taken to
    derive `fusion_leads`.
  - New helpers: `_row_candidate_kind(row)` (decode `metadata` the same fail-closed way
    `_candidate_score` decodes `ran_with_providers`) and `_fusion_leads_verdict(by_kind)`.
- `apps/scoreboard/portal/catalog.js` — extract the existing alpha comparator unchanged;
  partition `fusion_leads` benchmarks first, alpha comparator as the tiebreaker within each
  group (per the ticket: "don't change the existing alpha comparator, just partition before
  applying it").
- New test file `apps/scoreboard/tests/portal/catalog-fusion-order.test.js` (OME-798: one
  dedicated file per concern) covering the partition/tiebreak behavior, added by name to
  the `scoreboard` stack's `node --test` gate list in `.claude/sdlc.local.md` and to
  `.github/workflows/scoreboard-tests.yml`.
- New/extended Python tests in `apps/scoreboard/tests/unit/test_catalog_summary.py` for the
  fusion/model grouping (group-by-kind, unknown excluded, no-fusion / no-solo-model →
  false) — **blocked**, see Outcome.

## Test plan

- Python: benchmark with fusion max > model max → `fusion_leads=True`; fusion max < model
  max → `False`; only fusion submissions (no model) → `False`; only model → `False`; only
  `"unknown"` kind submissions → `False`; mixed specs where the per-spec-best selection
  (existing revision/case-count gating) excludes a stale row from the comparison.
- JS: a catalog mixing `fusion_leads: true/false/undefined` benchmarks sorts leading ones
  first, alpha order preserved within each partition, matching today's existing alpha
  comparator exactly.

## Acceptance

- `/v1/benchmarks/summary` rows carry `fusion_leads: bool`.
- The landing page's card grid shows fusion-leading benchmarks first, alpha order
  preserved as the tiebreaker, unchanged for the no-fusion-info case.
- `FEATURED_BENCHMARK_IDS` (`leaderboard-logic.js`, the per-benchmark-page tab strip) is
  untouched — out of scope per the ticket's own investigation notes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** none changed yet — implementation paused before the first edit; see
  below.
- **Commits:** none.
- **Gates:** not run (blocked before RED).
- **Deviations:** **STOPPED at the 95%-confidence / append-only gate, not self-approved.**

  Adding `fusion_leads` to `BenchmarkSummary` necessarily adds a new key to every row
  `GET /v1/benchmarks/summary` returns. The already-committed test
  `apps/scoreboard/tests/unit/test_catalog_summary.py::test_summary_matches_ranked_boards_and_omits_details`
  asserts the row's *exact* key set:

  ```python
  for row in rows:
      assert set(row) == {"id", "display_name", "description", "focus", "best_score"}
  ```

  That assertion must change to add `"fusion_leads"`, which is an edit to an
  already-committed test — the append-only gate this executor is told never to
  self-approve (`.claude/scripts/approved_test_changes.py`'s byte-exact
  `base_blob`/`approved_blob` manifest, the same mechanism OME-1852 used, recorded at
  `.claude/test-change-approvals/OME-1916.json` once approved). This is the *only* existing
  test this change touches — found by reading every test that enumerates
  `BenchmarkSummary`'s field set; no other prior test needed editing.

  Proposed exact edit (not applied):
  ```diff
  -        assert set(row) == {"id", "display_name", "description", "focus", "best_score"}
  +        assert set(row) == {
  +            "id", "display_name", "description", "focus", "best_score", "fusion_leads",
  +        }
  ```

  Everything else in this ledger (the catalog.py design, the new JS test file, the
  catalog.js partition) was designed and is ready to implement as soon as this one
  pre-existing assertion is confirmed. No code has been written; the worktree has no
  uncommitted changes beyond this ledger.
