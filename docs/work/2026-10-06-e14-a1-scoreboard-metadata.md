---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: blocked   # planned | in_progress | done | blocked — one open question, see Outcome
started: 2026-10-06
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.github/workflows/scoreboard-tests.yml` (one word added to
  the `node --test` line; the existing `test_portal_ci_wiring.py` requires every portal test file
  at both call sites). `routes/dependencies.py` also gained `verified_identity` and now owns the
  two identity detail strings (re-exported from `routes/scores.py`).
- **Commits:** see `git log --oneline e14-reproducible-submission-spec..HEAD`.
- **Gates:** ruff check, ruff format --check, pyright and the append-only check pass. pytest:
  `1 failed, 989 passed, 9 skipped`, coverage 90.23%. The one failure is the existing guard
  `test_every_score_field_reaches_at_least_one_read_dto`: the pinned `related_name="metadata_events"`
  adds a reverse relation to `Score._meta.fields_map` that the guard's `internal` set does not list.
  Fixing it needs an edit to an existing test (forbidden) or a change to the pinned related_name.
  Waiting for the orchestrator's decision. The node gate was not reached (the runner stops at the
  first red gate); run by hand it passes (66 tests).
- **Deviations:** the workflow file edit above; `uv run` for run_gates.py (PyYAML is not in the
  system python); `ScoreStore.metadata_row_query` added so a test can render the lock SQL.
