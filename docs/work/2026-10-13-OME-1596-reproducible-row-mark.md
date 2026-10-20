---
ticket: OME-1596
stack: scoreboard
status: done
started: 2026-10-13
finished: 2026-10-20
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
- **Commits** (by subject; the branch was rebased and squash-merge discards SHAs):
  `feat(scoreboard): store author and paper metadata and claim one score per frozen copy`;
  `feat(scoreboard): accept, validate, mask and edit author and paper metadata`;
  `feat(scoreboard): look a score up by its pinned cache and refuse a second claim on a copy`;
  `feat(scoreboard): offer a Reproduce button on captured rows`;
  `fix(scoreboard): let a same-owner retry racing its first send dedup` (the end-to-end
  regression below); `fix(scoreboard): validate and audit metadata scalar values correctly`;
  and the review-round-1 commits listed under "Review rounds".
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

## Rebase and pre-PR review — 2026-10-16

- Owner requested resolving conflicts, another review, and preparation for posting (not publishing).
- Rebased onto `origin/main` as of 2026-10-16. Backup ref:
  `backup/OME-1596-before-rebase-20261016-b9f846749`. Rebased code tip: the commit
  `fix(scoreboard): validate and audit metadata scalar values correctly`.
- Resolved only `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml`: retained
  main's `pareto-chart-launch-copy` and `benchmark-chart-isolation` tests alongside this branch's
  `reproduce-button` and `spec-meta-lines` tests. The previously approved reproduction-count
  test removal remains unchanged. No other implementation changes were needed for the rebase.
- Fresh review against current main and the current Linear description/comments covered metadata
  validation, masking/export compatibility, owner-only edits and audit/no-op semantics, copy
  claims/dedup, lookup visibility, migration ordering/duplicate refusal, and the #1406 portal
  integration. No additional blocking code finding identified. The Reproduce switch remains off.
- Validation: scoreboard gates green against rebased HEAD; repository gates green against
  `origin/main`; full Python run: **1324 passed, 9 skipped, 3 deselected**, coverage **91%**;
  all portal tests: **141 passed**. `git diff --check origin/main` clean. PostgreSQL-only tests
  were not rerun in this pass; earlier PostgreSQL manual evidence is recorded above.
- Branch-wide append-only check against `origin/main` accepts both approved Python test
  transitions and reports exactly the already-approved deletion of
  `tests/portal/reproduced-count.test.js`. No new exception introduced or hook bypass used.
  The owner's deletion exception still needs handling when pushing.
- Prepared PR body locally at `.docs/OME-1596-pr-body.txt` (gitignored), following the repository
  PR template. Suggested title: `feat(scoreboard): add credit metadata and pinned-cache replay lookup`.
  Suggested technical reviewer: `HupBaHa`; CI/shared-file co-owner: `sergio-bershadsky`.
- Before merge: read-only duplicate-copy checks on dev and production remain required. Deploy
  scoreboard before releasing OME-1613; enable the button only after that SDK release (`OME-1655`).
  No push, PR, review comment, Linear mutation, or deployment performed in this pass.

## Publishing approval — 2026-10-16

- Filip explicitly approved applying the recorded test-preservation exception for this push:
  "Yes, apply the recorded exception". The scope is the already-approved obsolete
  `tests/portal/reproduced-count.test.js` deletion, which the checker cannot represent;
  the two Python test transitions remain covered by the existing approval manifest.
- Final scoreboard gates passed with `--base origin/main --skip-append-only`, retaining
  lint, format, type, Python coverage, and portal checks; all repository gates also passed.
  No hook configuration change or general test-preservation exemption is authorized.
- Publish the rebased branch with an explicit lease on the pre-rebase remote tip (the commit
  `fix(scoreboard): let a same-owner retry racing its first send dedup`), verify the remote tip,
  then open the prepared draft PR. This does not authorize merge or deployment.

## Review rounds

### Round 1 — 2026-10-19 (PR #1440)

Findings and fixes (commits `fix(scoreboard): refuse unstorable metadata text and name the
Reproduce button by its label` and `docs(scoreboard): record review round 1 for OME-1596`):

1. Metadata text the store cannot hold reached the database: `{"title": "a\u0000b"}` answered 503
   on PostgreSQL (JSONB refuses NUL), and `{"title": "\ud800"}` answered 500 on SQLite with the
   row committed, after which every GET of it was a 500. `scores/credit_metadata.py` now refuses
   the NUL character and lone surrogates (detected by the UTF-8 encoder) in values, inner keys and
   `authors_metadata` keys, as a 422 naming the field and key, on submit, resubmit and PATCH. A
   key holding a lone surrogate is shown in the error location with the surrogate written out
   (`\\ud800`), so the 422 itself encodes. No general control-character ban. The pre-existing
   free-form `metadata` field is out of scope and unchanged.
2. The Reproduce button's accessible name did not start with its visible label (WCAG 2.5.3); it
   is now "Reproduce <spec>: copy the replay code".
3. OpenAPI descriptions for `authors_metadata` and `paper_metadata` on `ScoreSubmission`,
   `ScoreMetadataPatch` and `ScoreSchema` (known keys, limits, masking, whole-object replace,
   `null` clears on PATCH, `url` and `paper_url`).
4. Test gap: a one-object PATCH keeps the other object's event pair equal to the stored value,
   both directions; both tests fail when the fallback in `_log_metadata_event` is removed.
5. Test gap: the casefold-duplicate 422 carries `loc` and `input` (both spellings) as structured
   fields.
6. to 8. Test hygiene in this PR's own files: a test renamed to what it checks
   (`test_an_empty_page_reads_no_pinned_caches`); sync tests under the module asyncio mark made
   async; the 0021 refusal test no longer parses traceback text (exit status plus "nothing of 0021
   applied" checks; the message is asserted on the guard directly).
9. to 12. Docs: SHAs replaced by commit subjects in this ledger and the plan; spec section 6 names
   the shipped "Copy" label and section 5 records that the lookup takes no identity; the
   scoreboard README says the lookup answers 404 for private boards, owner included; the task
   mirror gains the 2026-10-16 and 2026-10-19 lines.

Not in this round (pending owner decisions): `frozen_copy_claimed` for private holders; the
switch-flip ticket.

Owner decisions, 2026-10-19 (docs only, commit `docs(scoreboard): record the 2026-10-19 owner
decisions for OME-1596`):

- The private-holder 422 is kept. The claim refusal is global, so a 422 `frozen_copy_claimed`
  reveals that some score (possibly on a private board) names that copy; accepted because copy
  ids are random UUIDs only their owner ever sees. Recorded in spec section 5.
- The NUL and lone-surrogate refusal is a row of the spec section 3 table.
- Turning the switch on is its own ticket, `OME-1655` ("Turn on the Reproduce button on the
  leaderboard", blocked by `OME-1613`). This ticket's acceptance: the button is present behind
  `SHOW_REPRODUCE_BUTTON`, shipped off. Spec sections 6 and 7 and the plan's rollout name
  `OME-1655`; a mirror `docs/tasks/2026-10-19-OME-1655-turn-on-reproduce-button.md` is added.

## 2026-10-19 — composed paper metadata limit follow-up (implemented; commit held)

- Intent: fix the reviewed P2 where 20 stored paper keys plus a separate `paper_url` edit
  produce a 21-key read object that cannot be submitted back unchanged. Owner approved the fix.
- Plan: validate the proposed complete paper object under the existing locked PATCH/resubmit
  paths, using the shared validator; map failures to structured 422s before any write/audit.
  Keep legacy URL-only rows and whole-object replacement/clearing unchanged. No migration.
- Test plan: new append-only route regressions for 19/20-key boundaries, unchanged round trips,
  failed-write atomicity, legacy URL-only rows, replacement/clearing, and the existing local
  round-2 byte cap when a separately supplied URL is composed with stored metadata.
- Scope: `scores/store.py`, `routes/scores.py`, a new
  `tests/unit/test_paper_metadata_composed_limits.py`, and this ledger. Existing uncommitted
  round-2 hardening in these files and other files belongs to another work session; preserve it.
- Acceptance: no successful paper edit yields an object outside the shared metadata bounds;
  refusals leave the row and edit log unchanged; all previous tests remain unchanged and pass.
- Outcome: added `_validate_proposed_paper_metadata` to both locked write paths and a shared
  `CreditMetadataInvalid` refusal, preserving the author-mismatch subclass and its wire error
  type. Invalid composed paper objects return 422 before any update or audit event. No schema,
  model, dependency, migration, or existing-test changes.
- RED: the new route file had four expected failures (key and byte limits on PATCH/resubmit),
  eight passes. GREEN: all 12 new cases pass. Complete local suite: 1,401 passed, 9 PostgreSQL
  tests skipped, 3 smoke tests deselected; coverage 91.50%. All 141 named portal tests pass;
  Pyright has zero errors/warnings; formatting and `git diff --check` pass.
- Required gate runner: `uv run .claude/scripts/run_gates.py scoreboard --base HEAD` passed the
  append-only check, then stopped on two pre-existing round-2 lint errors: PLR0911 in
  `_metadata_equal` and E501 at line 78 of `test_credit_metadata_review_round2.py`. Remaining
  checks were run individually; no gate was weakened or skipped to claim full green.
- Wisdom review: one shared validator sees the composed object under the already-held row lock;
  no trimming, new query, or alternate cap. Existing whole-object replacement, clearing,
  absent metadata, author-error shape, privacy and audit atomicity remain intact.
- Deviation/commit: left uncommitted because the worktree contains another session's unfinished
  changes in the same files and the full gate is not green. Those changes were preserved.
  No push, GitHub comment, Linear update, or production action performed.

## 2026-10-19 — independent verification before taking PR #1440 out of draft

- Owner requested full testing, another review, then ready-for-review only if clean. Reviewed
  the current remote head `22ce82888` and the combined local patch. Remote CI was green, but
  it does not include the uncommitted composed-paper fix or the other session's round-2 work.
- Re-ran the complete Python suite: 1,401 passed, 9 PostgreSQL tests skipped, 3 smoke tests
  deselected; 91.50% coverage. Pyright: zero errors/warnings. All 141 named portal tests pass.
  Ruff formatting: 164 files already formatted. `git diff --check` passes.
- Ran the nine CI PostgreSQL regressions separately against a new, isolated local PostgreSQL
  17 container: all nine pass. No production or development service was contacted.
- Independently reran the 45 new composed-paper/round-2 cases and four same-owner retry cases
  against PostgreSQL 17 in a temporary per-test-schema harness: all 49 pass. The initial
  harness setup was corrected to use `TortoiseContext` with explicit schema creation rather
  than `tortoise_test_context`, whose test-database creation expects a default database.
- **New P2, not fixed: byte-limit validation is not stable across JSONB numeric decoding.**
  `credit_metadata.stored_size` counts a float's scientific notation. Ten credited authors,
  each with twenty 64-character metadata keys holding `1.5e300`, fit in 15,401 encoded bytes
  and POST succeeds (201). PostgreSQL returns those whole-valued JSONB numbers as Python
  integers; the same full-email-key object then encodes to 74,001 bytes. PATCHing that stored
  object unchanged returns 422 (`authors_metadata`, at most 65,536 bytes). This failure is in
  the uncommitted round-2 hardening, not the remote draft's current head. Recommendation:
  make byte accounting stable across PostgreSQL numeric round trips, covering both spellings
  with a regression, without silently dropping metadata or weakening the cap.
- Local reproduction retained at
  `/tmp/pr1440-pg-review.0XrPo0/test_metadata_postgres_review.py`; with the isolated database
  running, use app cwd and `PYTHONPATH=src:tests/unit .venv/bin/python -m pytest -c pyproject.toml
  /tmp/pr1440-pg-review.0XrPo0/test_metadata_postgres_review.py -q --tb=short`. Final result:
  49 passed, one failed (the new numeric-size regression).
- Required gate runner still stops on the two existing round-2 lint failures: four returns
  in `_metadata_equal` (limit three), and the 101-character comment in the round-2 test file.
  No existing tests, lint limits, or gates changed. The historical approved deletion exception
  was not needed for these checks against HEAD.
- Review also rechecked locked write/audit atomicity, whole-object clearing/replacement,
  author masking, public pinned-cache visibility, unique-copy handling, narrow history reads,
  and the intentionally disabled Reproduce button. No additional blocking code finding.
  The documented dev/prod duplicate-copy audit remains required before merge.
- Outcome: **keep PR #1440 in draft**; the user's clean-verification condition is not met.
  Asked whether the other session's round-2 patch should be included when publishing; left
  that work intact pending confirmation. No commit, push, public review, or Linear mutation.

### Follow-up — include round-2 hardening, then publish only after clean verification

- Owner confirmed: "Include them if all checks pass." Include the existing round-2 patch,
  retaining its behavior and tests, together with the composed-paper correction.
- Plan before implementation: account for both incoming JSON and the integral-number spelling
  PostgreSQL JSONB returns when checking the 64 KiB envelope. Keep the larger encoded length,
  so neither spelling bypasses the bound. Do not mutate submitted values or change the cap.
  Add regression cases first, then fix the two lint failures without changing assertions.
  Update the spec/OpenAPI wording to document the round-2 limits already being included.
- Test plan: RED numeric-size/schema regressions; GREEN full Scoreboard gates, all CI PostgreSQL
  regressions, the temporary PostgreSQL metadata/retry harness including actual JSONB round
  trips. Review the complete staged patch and remote revision before publishing. Apply only the
  previously approved historical test-deletion exception if the push gate requires it.
- Outcome: retained all round-2 hardening and its assertions; fixed the two lint failures.
  Added JSONB-aware byte accounting without rewriting values. Decimal scale is preserved
  (`1.0` stays a float) while exponent values such as `1e23` are counted as PostgreSQL's
  expanded integers. The byte bound includes the composed paper URL under the write lock.
- RED: six expected numeric-size/schema failures and two passes. GREEN: nine permanent
  numeric-size tests, the 12 composed-paper regressions, and all 33 round-2 cases pass.
- Final complete Python run: **1,410 passed, 9 skipped, 3 deselected; 91.52% coverage**.
  The nine PostgreSQL-only skips were separately executed: **9 passed**. Temporary PostgreSQL
  metadata/retry harness: **51 passed**, including both rejecting the oversized numeric object
  before storage and accepting an unchanged smaller object after actual JSONB decoding.
  All **141 portal tests**, Ruff lint/format, Pyright, and repository gates pass.
- PostgreSQL 17 migration rehearsal (`/tmp/pr1440-pg-review.0XrPo0/migration_review.py`) passes:
  populated 0020 to 0021 adds all six JSONB columns, preserves scores and both child tables,
  leaves legacy metadata null, allows repeated null copy ids, and enforces unique non-null
  copy ids. A separate populated schema with duplicate copies refuses 0021 with none of its
  columns applied. This is local rehearsal, not the still-required dev/prod duplicate audit.
- Preservation check against the actual branch point `8edd994bf` reports only the already
  approved deleted portal test. A direct comparison to the newer `origin/main` also reported
  a main-only portal-test change; verified it is absent from this branch's diff. Full Scoreboard
  gates passed with `--base 8edd994bf --skip-append-only` under the existing approval, and the
  ordinary `--base HEAD` gates passed without any exception. No hook configuration changed.
- Final wisdom/review: shared validators, same transaction/row lock, no new schema or dependency,
  bounded errors, exact numeric comparisons, narrow history reads, unchanged masking/privacy
  and null/absent behavior. No remaining blocking code finding. Keep the Reproduce switch off
  and require the documented dev/prod duplicate-copy audit before merge. Commit/push the combined
  fix, verify the exact remote SHA and CI, then mark the existing PR ready; do not merge or post
  a public review.

### Dmitry review follow-up — email keys and accessible copy feedback

- PR #1440 was published ready at `2f156bbf1`. Dmitry identified missing email syntax validation,
  contradictory resubmit-null documentation, and inaccessible clipboard outcome feedback.
- Owner agreed to email-key validation, requested a plainer explanation of the null decision,
  and approved the accessibility fix if small. Implement only the first and third items now.
  Keep resubmit-null behavior unchanged and its contract decision explicitly unresolved.
- Before implementation: add API regressions including auth-disabled `submitted_by=not-an-email`
  with an identical metadata key; cover resubmit/PATCH, valid spellings, and legacy submissions
  without metadata. Reuse the existing AuthorEmail rule rather than introducing a second regex.
- Add a new named portal test for both copy actions, success/failure, initial live-region presence,
  label reset and repeated announcements. Use the existing sr-only style, keep Reproduce off.
- Verify RED first, then full Scoreboard/repo gates and a focused self-review. No public review,
  GitHub thread resolution or merge; the null decision and deployment audit remain outstanding.
- RED: seven Python regressions failed (the malformed key was stored on all three write paths;
  four malformed spellings passed the pure validator); three valid/compatibility cases passed.
  Six portal cases failed because no live region existed. Fixed the new PATCH test's missing
  identity header before recording these failures, so it reached the intended write path.
- GREEN: all ten new Python cases and six new portal cases pass. Full `scoreboard --base HEAD`
  and `repo` gate runs passed: preservation, ruff, format, pyright, pytest with coverage, all
  named portal tests, and repository process checks. No test-preservation exception needed.
- Wisdom/self-review: one AuthorEmail type and regex shared with request schemas; existing
  size/storability guards, casefold matching and legacy submitter compatibility retained.
  Clipboard text is still copied verbatim, feedback is textContent-only, styling unchanged,
  and Reproduce remains off. Live-region structure follows W3C ARIA22; tested with the DOM
  harness, not an actual screen reader. No schema, transaction, SDK or null-semantics changes.
- Outcome: commit the two approved fixes locally; no push or public comment. Point 2 still
  needs an owner decision and aligned documentation before requesting reviewer sign-off.

### Owner decision — resubmission preserves null metadata (2026-10-19)

- Owner approved the recommendation: "let's go with the recommendation, and update where
  needed (spec, right?)". This resolves point 2 of Dmitry's review and supersedes the earlier
  plan wording that treated resubmit-null as clearing. Earlier ledger entries above remain
  historical, not evidence that this decision was already approved then.
- Planned: align spec, plan, task mirror and submission OpenAPI descriptions. For each metadata
  object, same-owner resubmit with null or omission preserves it; PATCH null clears it and
  PATCH omission preserves it. A supplied object still replaces it whole, including `{}`.
  Clearing paper metadata through PATCH also clears its link. Other explicitly supplied fields
  and author-removal pruning retain their existing rules. No runtime or migration change.
- Verification plan: add an API characterization test for explicit-null resubmit preserving
  existing objects and link, alongside existing omission and PATCH-clear tests; run focused
  tests and full Scoreboard/repo gates. This test should already pass: the mismatch is in the
  documentation, not the implementation. Keep this follow-up local; no public comments or merge.
- Outcome: updated all six planned files. The explicit-null API regression passed before the
  OpenAPI wording change; all 20 tests in `test_score_credit_metadata.py` passed. Full
  `scoreboard --base HEAD` and `repo` gates passed, including test preservation without exception,
  lint/format, type checks, Python coverage and the named portal suites.
- Wisdom/review: runtime semantics and existing tests remain unchanged; the spec now scopes the
  rule to these two metadata fields, documents `{}` replacement and paper-link effects, and
  records the actual approval date rather than retroactively claiming earlier approval.
  Point 2 is resolved locally. Reviewer sign-off and the existing pre-merge deployment audit
  remain separate; this commit does not claim the PR is approved or ready to merge.

### Pinned-cache visibility race — latest review, 2026-10-19

- Owner requested fixing Dmitry's additional blocking finding at `ba48c8673`: the pinned-cache
  lookup lacked the route-level final visibility check used by the existing public score reads.
- Plan before code: append deterministic API regressions that pause after the real store read,
  flip the board to private, resume, and compare status/body/cache headers against unknown and
  already-private lookups. Cover anonymous, owner and another caller; the route is public-only.
  Also cover OperationalError during initial lookup and the added final visibility read.
- Implement the existing `turned_private` helper as the last await before serialization, inside
  the route's OperationalError boundary. Keep `_score_not_found()` for every privacy refusal.
  Correct store/route comments that overstate the initial read's guarantee; no models, migrations,
  locking changes, portal changes or new identity exemptions. Follow existing read-time privacy
  semantics, not a claim that visibility remains locked through network response delivery.
- Verification: RED first; focused pinned-cache and visibility suites, then full Scoreboard/repo
  gates, test preservation, self-review and local commit. No public review or merge.
- RED: all three caller variants leaked 200 during the forced flip, and the final-read error
  case returned 200 instead of 503. The existing initial-lookup error case already passed.
- Fix: final `turned_private` check and serialization now share the OperationalError boundary.
  All 18 pinned-cache tests pass. The complete Python run had 1,425 passes, nine PostgreSQL skips,
  three smoke deselections, 91.61% coverage, and one failure: the static visibility-exit guard.
  Lint, formatting, typing and append-only checks passed before that failure.
- Guard checkpoint: corrected docstrings cause the static survey to include these previously
  overlooked functions. Keeping serialization inside the guarded try makes the successful route
  return recognized without changing the analyzer. Remaining entries needing documented reasons
  are exactly two route raises (malformed-id 404 and database-error 503), and two store-helper
  returns (initial private/unknown filter or candidate returned to the revalidating route).
  Focused rerun: 21 passed, only that guard failed. Do not exempt the successful route return.
- Paused before editing the existing guard's `EXPECTED_UNGUARDED` list: SDLC rule 5 requires owner
  approval for changes to a prior test. Proposed change is only these two reasoned entries;
  no analyzer change, skipped test, or assertion removal. Nothing committed or pushed yet.
- Owner approved those guard entries, rerunning checks and committing ("yes", 2026-10-19).
  Record only the byte-exact guard transition in the existing approval manifest; no broader
  exemption. Then rerun the focused suite, complete Scoreboard/repo gates and review the diff.
- GREEN after approval: all 22 focused pinned-cache/visibility-guard tests pass. Both complete
  gate runners pass against the pre-fix HEAD: Scoreboard append-only (exact approved guard
  transition), ruff lint/format, pyright, pytest with coverage threshold and portal Node tests;
  repo script tests, loop parity and task-mirror checks. `git diff --check` is clean.
- Self-review: the final visibility read is the last await before the successful response;
  unknown and newly-private rows share the existing refusal, including cache headers. Both
  database failure stages are sanitized. The guard's successful-return protection remains
  active; only the two owner-approved exception entries changed. Existing tests are retained.
  No schema, identity, shared-helper or deployment changes. No further finding in this fix.
- Wisdom: an initial store filter is not a visibility lock. Public routes must make their
  final read-time privacy decision at serialization, without claiming delivery-time locking.
- Ready for a local commit only; no push, public review, merge or deployment in this step.

## Rebase onto main (2026-10-19)

- PR #1440 was approved and green but conflicted with `e003f254a` (anonymous score reads moved to
  `GET /v1/public/scores/{id}` because prod Cloudflare Access gates every `/v1/scores` subpath).
- The 18-commit branch was folded into one commit (backup branch `OME-1596-backup-pre-rebase-20261019`)
  and rebased. Conflicts: `routes/scores.py` (kept main's `_read_score` + public alias, added the
  lookup), `test_visibility_exit_guard.py` (kept both exemptions), `reproduced-count.test.js`
  (stays deleted: this PR removes the count).
- **The pinned-cache lookup moved to `GET /v1/public/scores/by-pinned-cache/{frozen_copy_id}`**, so
  an anonymous replay is not sent to the Access login. README, schema docstring, spec (dated note),
  plan and tests updated; new test asserts the old path does not serve the lookup. The PR's own
  portal test `spec-meta-lines` now fakes `/v1/public/scores/{id}` like main's portal.
- Gates: ruff, format, pyright, pytest 1,443 passed (91.62% coverage), portal tests all pass.
  `run_gates.py` append-only check flags 4 prior tests the PR already changed (reproduced-count
  deleted, the guard exemption, `test_score_metadata_events.py`, `test_score_reproductions.py`) —
  all from the approved PR, not from the rebase; owner decision pending.

## Merge and close (2026-10-20)

- PR #1440 squash-merged as `c33df414f` on owner instruction. CI was green. Its single commit
  was pushed at 21:03 on 2026-10-19, after the last approval at 14:15; the owner chose to merge
  without asking for re-approval.
- **Deviation: rollout step 1 (the read-only duplicate `frozen_copy_id` query on dev and
  production) was not run before the merge.** Dev evidence afterwards: dev rolled the new build,
  serves `GET /v1/public/scores/by-pinned-cache/{frozen_copy_id}` and answers 404 for an unknown
  id, so migration 0021 ran there; 0021 refuses on any duplicate, so dev had none. Production has
  not been checked; the query stays a required step before the production deploy.
- Dev has no public rows, so the lookup could not be exercised against a real captured score
  there. Production (old build) has 40 public rows, none with `pinned_cache` yet, as expected.
- Ticket closed on owner instruction: the code is merged and the Reproduce button ships off.
  The production deploy gates the SDK release (`OME-1613`), not this ticket.
