# Revision selector on each leaderboard — OME-1708

Decisions 1–8 are in the ledger `docs/work/2026-11-17-revision-dropdown.md`; mockups are in
`docs/spec/2026-11-17-revision-dropdown/mockups/` (published for product review at
https://claude.ai/artifact/VTP23xFifCTgQa2scbe58S).

## Why

A leaderboard shows only its benchmark's current revision
(`scores/store.py:1035`). When a revision moves, every result under the old id disappears.
OME-1909 makes that routine: a grading change bumps the revision, and old results are
re-graded from their pinned caches; its 2026-11-17 decision shows revisions through this
selector.

## Behaviour

### Benchmark page (`portal/benchmark.html`)

- **Placement:** under the title, above the stats (mockup A). Picking a revision changes the
  stats, score bars, frontier chart, legend and table together.
- **One revision:** plain text, "Revision a41c09e2 · since 9 Oct 2026". **Two or more:** a
  dropdown.
- **Options**, current first, then other revisions by descending first-seen date:
  - "Latest · since 17 Nov 2026 · a41c09e2 · 9 results"
  - "Previous · 9 Oct – 17 Nov 2026 · 32a91cf1 · 12 results"
  - Older revisions follow, labelled by date range only.
  - The date is when the scoreboard first saw the revision. A backfilled date is the first
    submission under it, shown with "about" before it (e.g. "since about 9 Oct 2026").
- **Default:** Latest. The choice lives in `?revision=<full id>` and is updated without a
  reload; no parameter means Latest. An unknown revision in the URL falls back to Latest,
  with the line "Revision 1234abcd is not on this leaderboard."
- **Empty Latest:** after a bump, Latest stays selected and shows "No results under this
  revision yet. 12 results under 32a91cf1 (previous) — show them.". The link switches the
  selector. There is no automatic fallback and no mixing of revisions.
- **No "All revisions" choice.**

### Submission history page (`portal/spec.html`)

- Every run of the recipe stays listed, newest first.
- A new **Revision** column shows the short id, with a "latest" tag on the current
  revision. Rows under older revisions are dimmed, and the id links to
  `benchmark.html?id=…&revision=…`.

### Completeness

- Every revision's board ranks only complete runs, the same rule as today's board
  (OME-1056: `total_questions >= case_count`). With an authoritative count, partial
  runs never appear; historical inferred counts have the limitations below.
- A new revision's Case count is recorded when the scoreboard first sees it.
- An older revision's count is backfilled once as the largest `total_questions` among its
  results, and marked inferred. This is a heuristic: the API accepts client-supplied
  counts, so an oversized run can inflate it and all-partial runs can underestimate it.
  Neither MAX nor mode proves coverage.
- Failed Cases do not change this. A failed Case stays in the run, scored 0 with its
  failure recorded, and the SDK submits `total_questions = len(cases)`
  (`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:802`). A full run
  with failures is complete and ranks with its lower score, as today; only `limit=n` runs
  are partial. Runs on hand-picked Cases cannot be submitted (`leaderboards.py:789-792`).

## API

- **`GET /v1/leaderboard/{id}/revisions` (new):**
  - Returns, current first: `revision`, `first_seen_at`, `first_seen_inferred`,
    `until` (the next chronological first-seen date; null for current or unknown end dates),
    `case_count`, `case_count_inferred`, `result_count`, `current`.
  - `result_count` uses a SQL count over the ranked query, without loading recipes.
    For the current revision it uses the live registered Case count, including null,
    so it always matches the default board.
  - Rollback A → B → A puts A first with `until: null`. First-seen dates do not move.
    The end of B is unknown (null), because activation/rollback times were not recorded.
  - Private boards follow the same visibility rule as the leaderboard route.
- **`revision` query parameter** on `GET /v1/leaderboard/{id}` and
  `GET /v1/leaderboard/{id}/frontier`:
  - Absent means the registered revision; existing calls are unchanged.
  - Present: the board, frontier and completeness check use that revision and its recorded
    Case count. The store already takes both as arguments
    (`store.leaderboard(registered_revision=…, registered_case_count=…)`,
    `store.py:2212`; `leaderboard_pareto_inputs`, `:2275`).
  - An unknown revision returns 404 with a problem body. Boards without a registered
    revision return an empty revision list and reject any explicit selection.
  - Backfilled historical ids are client assertions, not proof of a registered revision.
    Their boards remain browsable with inferred counts, but inferred or unknown historical
    counts never receive frontier badges or frontier statistics. Seed-recorded historical
    counts can support frontier claims. Current-revision behavior remains unchanged.
- **`GET /v1/leaderboard/{id}/{spec}/history`:** unchanged. Each row already carries
  `benchmark_revision`; the page learns which revision is current from `/revisions`
  (`current: true`). Two existing tests pin this response's exact shape.
- **Private boards:** `/revisions` answers 404, like `/frontier`, because per-revision
  result counts describe every participant (OME-894). Visibility is re-read after the
  counts and before the response.

## Storage

- **New model `BenchmarkRevision`**, one row per (benchmark, revision):
  - `first_seen_at`, `first_seen_inferred`, `case_count` (nullable),
    `case_count_inferred`.
  - Unique on (benchmark, revision).
- **Recorded from now on:** `store.register_benchmark` (the seed job's write,
  `seed.py:560-615`) inserts the row the first time it sees a (benchmark, revision), with
  the Engine's Case count. It never overwrites an existing row, so a past revision's count
  survives the next bump.
- **Backfilled by the migration:**
  - For every distinct (benchmark_id, benchmark_revision) in `scores`, plus each
    benchmark's registered revision, insert one row, only for boards with a registered revision.
  - `first_seen_at` is MIN(`submitted_at`), marked inferred.
  - `case_count` is the registered count for the current revision; for older revisions it
    is MAX(`total_questions`), marked inferred.
  - Scores with a null revision are left out.
- **Migration number:** the next free one (0024). OME-1909 and source-health PR #1749
  also plan 0024; whichever
  lands second renumbers.
- **Deleting a benchmark:** the revision rows cascade with it. `retire_benchmark` and
  `purge_private_benchmark` delete them explicitly first, in the same transaction. On
  SQLite, cascaded rows count in the delete count, which their exactly-one-row checks
  would otherwise refuse.

## Out of scope

- An "All revisions" view.
- Re-grading old results (OME-1909).
- Splitting or relabelling historical scores that share an id but may have used different
  graders. The ticket forbids it without evidence of the grading used.
- Hand-written revision names.

## Risks

- **Inferred Case counts:** if every result under an old revision is partial, the inferred
  count is too small and those partial runs would rank. In that case the board shows
  "Case count inferred from results", and the revisions route marks it. Oversized
  reported counts can instead exclude legitimate full runs. No frontier claim is made
  for these historical scopes; authoritative backfill requires independent evidence.
- **Clock:** `first_seen_at` for new revisions is the seed job's time, which can trail the
  Engine deploy by minutes. That's fine for a date label.

### Read-only pre-deploy count audit

Run against the production database before accepting the historical MAX counts.
This reports past-revision groups where the largest reported count differs from
the most common count (ties choose the larger count). It reports no submitter data.
A mismatch needs evidence of canonical coverage; mode is not proof either.

```sql
WITH frequencies AS (
    SELECT s.benchmark_id, s.benchmark_revision, s.total_questions, COUNT(*) AS runs
    FROM scores AS s
    JOIN benchmarks AS b ON b.id = s.benchmark_id
    WHERE b.revision IS NOT NULL
      AND s.benchmark_revision IS NOT NULL
      AND s.benchmark_revision <> b.revision
    GROUP BY s.benchmark_id, s.benchmark_revision, s.total_questions
), counts AS (
    SELECT *,
        MAX(total_questions) OVER (PARTITION BY benchmark_id, benchmark_revision) AS maximum,
        ROW_NUMBER() OVER (
            PARTITION BY benchmark_id, benchmark_revision
            ORDER BY runs DESC, total_questions DESC
        ) AS preference
    FROM frequencies
)
SELECT benchmark_id, benchmark_revision, maximum, total_questions AS modal_count
FROM counts
WHERE preference = 1 AND maximum <> total_questions
ORDER BY benchmark_id, benchmark_revision;
```
