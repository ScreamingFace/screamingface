---
ticket: OME-1596
stack: scoreboard
status: in_progress
started: 2026-10-13
finished:
---

# OME-1596 — author and paper metadata, and a Reproduce button, on the leaderboard

## Intent

Scoreboard half of the E14 follow-up agreed with Irina (2026-10-14/15): submitters can attach
`authors_metadata` and `paper_metadata` (open objects with known keys, bounded, matched to `authors`,
masked in public JSON, editable with the edit log); a public lookup from a pinned cache id to its
published score lets the SDK's `evaluate(pinned_cache=…)` (`OME-1613`) replay and judge; each fully
captured public row gets a Reproduce button behind a switch; the "Reproduced N times" line goes. Spec:
`docs/spec/2026-10-13-OME-1596-reproducible-row-mark.md` (owner-approved piece by piece, 2026-10-15).

The 2026-10-13 version of this unit (a reproducible / reproduced row mark) was dropped before any code.

## Planned changes

Plan: `docs/plan/2026-10-15-OME-1596-metadata-and-reproduce.md` (rows 2 to 5, one commit each).

- Storage: `scores/models/score.py`, `scores/models/score_metadata_event.py`, migration
  `scores/migrations/0021_score_metadata_objects.py` (six JSON columns, unique `frozen_copy_id`,
  duplicate guard), `scores/schemas.py` (read fields, so no column is missing from every read DTO).
- Metadata: new `scores/credit_metadata.py` (the shared validator), `scores/schemas.py`,
  `scores/store.py`, `routes/scores.py`.
- Lookup: `routes/scores.py`, `scores/store.py`, `scores/schemas.py`.
- Rows and portal: `routes/leaderboard.py`, `portal/benchmark.js`, `portal/spec.js`, a new Node
  test file listed in `.github/workflows/scoreboard-tests.yml` and `.claude/sdlc.local.md`.
- Tests: new files under `apps/scoreboard/tests/unit/` and `apps/scoreboard/tests/portal/`.

## Test plan

Spec §7.

## Acceptance

Spec §7 and the Linear issue's acceptance list.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Row 2 (storage): `scores/models/score.py`, `scores/models/score_metadata_event.py`,
    `scores/migrations/0021_score_metadata_objects.py`, `scores/schemas.py` and `scores/store.py`
    (read fields); tests `tests/unit/test_migration_0021_metadata_objects.py`,
    `tests/unit/scores/test_metadata_columns.py`.
  - Row 3 (metadata): new `scores/credit_metadata.py`; `scores/schemas.py`, `scores/store.py`,
    `routes/scores.py`; tests `tests/unit/scores/test_credit_metadata.py`,
    `tests/unit/test_score_credit_metadata.py`; spec section 3 gains (b) and (c).
  - Row 4 (lookup): `routes/scores.py`, `scores/store.py`, `scores/schemas.py`; test
    `tests/unit/test_pinned_cache_lookup.py`.
  - Row 5 (rows and portal): `routes/leaderboard.py`, `scores/store.py`,
    `portal/leaderboard-logic.js`, `portal/main.js`, `portal/benchmark.js`, `portal/spec.js`,
    `portal/portal.css`; tests `tests/unit/test_leaderboard_pinned_cache.py`,
    `tests/portal/reproduce-button.test.js`, `tests/portal/spec-meta-lines.test.js`;
    `tests/portal/reproduced-count.test.js` deleted; `.github/workflows/scoreboard-tests.yml` and
    `.claude/sdlc.local.md` list the two new Node files.
  - Approved prior-test changes: `.claude/test-change-approvals/OME-1596.json`.
- **Commits:** `8b8ee2246` storage; `8fa82a70c` metadata; `73f0cca3c` lookup; `0a7eb0feb` rows
  and portal; then `fix(scoreboard): let a same-owner retry racing its first send dedup` (the
  end-to-end regression below).
- **Gates:** rows 2 to 4: `run_gates.py scoreboard --base origin/main` all green. Row 5: every
  scoreboard gate green (ruff, format, pyright, pytest with coverage, the Node portal suite);
  the append-only check reports only the owner-approved deletion of
  `tests/portal/reproduced-count.test.js`, which cannot be blob-approved, so it rides the
  owner's `--skip-append-only` press (the OME-1460 precedent). `run_gates.py repo` green.
- **Deviations:**
  - The unique rule on `scores.frozen_copy_id` is a constraint (`unique_together` on the model,
    `AddConstraint` in 0021), not `unique=True` on the field: an AlterField rebuilds `scores` on
    SQLite and drops it under the foreign keys pointing at it. Owner accepted, 2026-10-15.
  - Row 2 also adds `authors_metadata` and `paper_metadata` to `ScoreSchema` (excluded when null)
    and to `_score_to_schema`, because the prior test
    `test_every_score_field_reaches_at_least_one_read_dto` fails for a Score column no read DTO
    carries. Masking stays in row 3. Owner accepted, 2026-10-15.
  - Three prior tests needed changes the spec forces; owner approved all three on 2026-10-15
    (two in row 2, `reproduced-count.test.js` in row 5), recorded in
    `.claude/test-change-approvals/OME-1596.json`.
  - Migration 0021 and its guard were also exercised by hand on PostgreSQL 17 (docker): the guard
    refused a board with a duplicate copy and applied nothing; after the duplicate was cleared, it
    applied, and a second score naming the same copy was refused by the constraint.
  - Row 3, owner decisions of 2026-10-15 the spec left open (spec section 3 gains (b) and (c)):
    (a) `paper_metadata.url` and `paper_url` disagreeing is a 422; `paper_metadata` without `url`
    clears `paper_url`; `null` clears both; a url alone stores `paper_metadata` as `{}`.
    (b) two `authors_metadata` keys equal after casefolding are a 422 naming the field and both
    keys. (c) without `authors`, keys match the shown credit line (`authors`, or
    `[submitted_by]`), checked in the store under the row lock on submit, resubmit and PATCH.
  - Row 3: `_validate_paper_url` moved unchanged from `schemas.py` into the new
    `scores/credit_metadata.py` (imported back under its old name) so `paper_metadata.url` and
    `paper_url` share it without a circular import. A resubmit treats a missing object as "not
    given" (the existing resubmit rule), so `null` clears only through PATCH. The edit-log event
    fields for the objects are excluded when null, so events about `authors` or `paper_url`
    alone read as before. The history route (`HistorySubmission`) carries no metadata: it does
    not carry `paper_url` either, and the spec page reads both from `GET /v1/scores/{id}`.
  - Row 4: the lookup answers `score_id`, `benchmark_id`, `benchmark_revision`,
    `url4_expression`, `answer_seed`, `score`, `total_questions`, `case_digest` and
    `capture_status` (`PinnedCacheSchema`). It takes no identity, so a private board's own
    submitter also gets the 404. The public/private decision lives in the store
    (`public_score_for_pinned_cache`, reading the board last) rather than the route, so the
    route has no exit for `test_visibility_exit_guard` to list. The claim refusal is a pre-check
    in the write's transaction plus a mapping of the unique-index violation, decided by querying
    who holds the copy (never by the database error's text). Both paths, and the replay fill,
    were also exercised by hand on PostgreSQL 17 (docker); the shared `tortoise_db` fixture
    cannot run on PostgreSQL (OME-430), so CI covers them on SQLite.
  - Row 5: `RankedLeaderboardEntry.pinned_cache` is excluded when null rather than served as
    `null`, so a row with nothing to replay keeps the row shape the prior test
    `test_ome894_guard_public_board_is_unchanged_anonymously` pins; a client reads absent and
    null alike (no Reproduce). The Run cell is built by `renderRunCell(entry, showReproduce)`,
    exposed with the switch on `window.SFBenchmarkPage` so the portal tests can render both
    settings without editing the shipped constant. `createCopyButton` gained optional
    `ariaLabel` and `title`; the existing Copy button is unchanged.
  - Regression found end to end after row 5: one owner sending the same submission with a
    frozen copy several times at once got [201, 422, 422, 422, 422, 422] on PostgreSQL 17
    (SQLite intermittent). The copy pre-check saw the row the first send had just committed and
    refused before the insert's content-hash clash could route the retry to the dedup path. The
    pre-check now leaves out a holder of the same recipe (same content hash); a different holder
    is still refused. Regression test `tests/unit/test_pinned_cache_same_owner_race.py` drives the
    race deterministically (the first dedup lookup misses while the row exists). The coordinator's
    `samerace.py` now gives [200, 200, 200, 200, 200, 201] with one id, three rounds each, on
    SQLite and on a throwaway postgres:17 container.

## Review follow-up — 2026-10-16

Owner approved fixing the two localized P2 findings before drafting the PR.

- Plan: avoid float conversion when validating finite integer metadata; compare metadata as
  JSON so boolean/number changes are saved and audited on PATCH and same-owner resubmit.
- Add API regression tests first for large integers in both objects and both write paths,
  boolean/number replacements and audit timestamps, and key-order-independent no-op retries.
- Run the scoreboard gates with append-only checked against this iteration's starting HEAD.
  No schema change, main rebase, PR creation, or public review comment is part of this fix.
- Outcome: fixed both P2s in `scores/credit_metadata.py` and `scores/store.py`; added
  `tests/unit/test_credit_metadata_scalar_regressions.py` (32 parametrized cases). Initial RED:
  20 failures reproducing the reported bugs, four existing no-op cases passing. Final GREEN:
  all 32 pass, including eight additional equal-number no-op cases.
- Review refinement: JSON string comparison would distinguish `1` from `1.0`; an additional
  RED test demonstrated the unwanted audit entries. The final bounded-object comparison keeps
  numeric equality and key-order independence, while distinguishing booleans from numbers.
- Gates: `uv run .claude/scripts/run_gates.py scoreboard --base HEAD` all green (append-only,
  ruff lint/format, pyright, full pytest with coverage, named Node portal suite); `git diff
  --check` clean. Prior tests unchanged; no new dependency, schema, auth, or visibility change.
- Commit: `fix(scoreboard): validate and audit metadata scalar values correctly`.
  This follow-up is complete locally; the overall feature remains in progress. Existing main
  conflicts and deployment duplicate-copy checks remain separate pre-PR/pre-merge work.
