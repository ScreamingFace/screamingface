---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# e14-a1-scoreboard-metadata — paper link, owner edit and edit log on the scoreboard

## Intent

E14 PR A1. A researcher who submits before the paper exists can add `paper_url` and fix `authors`
later, as the verified submitter only. Each change writes one row to a new edit log that only the
owner can read. Spec: `docs/spec/2026-10-06-e14-reproducible-submission/prd/metadata-ownership.md`
(M1-M21, TDD #1-#18). Plan: `docs/plan/2026-10-06-e14-reproducible-submission/A1-scoreboard-metadata.md`.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/migrations/0019_score_metadata.py` (new)
- `apps/scoreboard/src/scoreboard/scores/models/score.py`, `score_metadata_event.py` (new), `models/__init__.py`
- `apps/scoreboard/src/scoreboard/scores/schemas.py`, `scores/store.py`
- `apps/scoreboard/src/scoreboard/routes/dependencies.py`, `routes/scores.py`
- `apps/scoreboard/portal/spec.js`
- tests: `tests/unit/test_score_paper_url.py`, `test_score_metadata_patch.py`,
  `test_score_metadata_events.py`, `tests/portal/paper-link.test.js`
- `.claude/sdlc.local.md` (add the new JS test to the `node --test` gate line)

## Test plan

TDD table #1-#18 of the PRD, in order. #1 and #2 are CHAR (pass on today's code).

## Acceptance

- `python3 .claude/scripts/run_gates.py scoreboard --base e14-reproducible-submission-spec` is green.
- Local only: nothing pushed, no PR, no Linear change.

## Pinned-decision notes

- `ScoreMetadataEvent.score` uses `related_name=False` (coordinator decision, 2026-10-06; it
  replaces the plan's `related_name="metadata_events"`). WHY: nothing uses the reverse accessor,
  and a reverse relation adds a `Score` field that the existing guard
  `test_every_score_field_reaches_at_least_one_read_dto` would flag. The store queries events by
  `score_id`. Migration 0019 matches.
- The event log records the RAW stored values (it records what the row held). A row with NULL
  `authors` that gets `authors: [submitted_by]` therefore counts as a change and writes an event,
  although a read shows `[submitted_by]` both before and after. Accepted by the coordinator.

## Design-review round (coordinator, 2026-10-06)

Fixes 1-8, 10, 11 and 14 applied in one round, each behaviour change with a new test (no existing
test edited): README auth statement and node line; `patch_metadata` re-checks the board inside the
transaction (`_revalidate_visibility(..., lock=True)`, board locked before the score row; a mismatch
is a 409, new params `benchmark_id` and `expect_private`); `_load_owned_score` treats a missing
board row as private and returns `(score, private)`; owner-only `responses=` document the 401 (both
modes) and both 403 shapes (`CodedErrorResponse` added); one clock read for `metadata_updated_at`
and the event's `edited_at` on both write paths; events ordered by `-edited_at, -id`; `PaperUrl`
rejects any whitespace and any user info; `authors: null` 422 points at `body.authors`;
`_log_metadata_event(source: Literal["patch","resubmit"])`; `get_score` uses `_score_not_found()`;
PATCH 200 on a private board carries `PRIVATE_CACHE_HEADERS`. Items 9, 12, 13, 15, 16, 17 left
as they are.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.github/workflows/scoreboard-tests.yml` (one word added to
  the `node --test` line; `test_portal_ci_wiring.py` requires every portal test file at both call
  sites). `routes/dependencies.py` also owns the two identity detail strings (re-exported from
  `routes/scores.py`). Accepted by the coordinator.
- **Commits:** see `git log --oneline e14-reproducible-submission-spec..HEAD`.
- **Gates:** `ALL GATES GREEN` (`uv run .claude/scripts/run_gates.py scoreboard --base
  e14-reproducible-submission-spec`): append-only check, ruff check, ruff format, pyright, pytest
  with coverage, and the `node --test` gate including `paper-link.test.js`. 9 PostgreSQL tests skip.
- **Deviations:** the workflow-file edit; `uv run` for run_gates.py (PyYAML is not in the system
  python); `ScoreStore.metadata_row_query` added so a test can render the lock SQL;
  `related_name=False` on the event FK (see Pinned-decision notes). All accepted.
