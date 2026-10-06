---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# e14-b4-scoreboard-cache-version — cache version columns and recorded reproductions on the scoreboard

## Intent

E14 PR B4. A submission stores the cache revision of its run, whether the run is fully replayable
(`reproducible`), and its answer seed, as fill-only columns. A verified identity can record an
exact replay of a `complete` score through a new endpoint; the score read shows how many times it
was reproduced and when last. Spec: `docs/spec/2026-10-06-e14-reproducible-submission/prd/cache-version-capture.md`
(C4, C10, C12; TDD #16-#18) and `prd/reproduce.md` (R4, R6, R12-R15, R18, R22; TDD #7-#14).
Plan: `docs/plan/2026-10-06-e14-reproducible-submission/B4-scoreboard-cache-version.md`.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/migrations/0020_score_cache_version.py` (new)
- `apps/scoreboard/src/scoreboard/scores/models/score.py`, `score_reproduction.py` (new), `models/__init__.py`
- `apps/scoreboard/src/scoreboard/scores/schemas.py`, `scores/store.py`
- `apps/scoreboard/src/scoreboard/routes/scores.py`
- `apps/scoreboard/portal/spec.js`
- tests: new files only, `tests/unit/test_score_cache_version.py`,
  `tests/unit/test_score_reproductions.py`, `tests/portal/reproduced-count.test.js`
- `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml` (add the new JS test to the
  `node --test` line; `test_portal_ci_wiring.py` requires both)

## Test plan

TDD tables: cache-version-capture #16-#18, then reproduce #7-#14, in that order. Tests are
append-only: no existing test is edited.

## Acceptance

- `uv run .claude/scripts/run_gates.py scoreboard --base e14-a1-scoreboard-metadata` is green.
- Local only: nothing pushed, no PR, no Linear change.

## Pinned-decision notes

- `ScoreReproduction.score` uses `related_name=False` (as A1's event model): a reverse relation
  would add a `Score` field that `test_every_score_field_reaches_at_least_one_read_dto` flags.
- The label and the status fill together, gated on the STATUS: a row that already holds
  `partial` with no label is not given a label by a later replay. `answer_seed` fills alone.
- `reproduction_count` is `exclude_if` zero and `last_reproduced_at` is excluded when null
  (coordinator, 2026-10-06; it replaces the plan's plain `int = 0`). An absent count reads as 0
  (K8). It is filled only by `GET /v1/scores/{id}`, so a row with no reproductions serializes
  byte-identically in the private export and in PATCH and resubmit responses.
- A repeated `(score_id, run_id)`: the SAME verified identity gets 200 with the existing row; a
  DIFFERENT identity gets 409 `run_id_conflict` with nothing about the first row
  (`ReproductionRunIdConflict` in the store).
- The board is re-checked inside the insert transaction, under its lock, as `patch_metadata` does
  (`BenchmarkVisibilityChanged` -> 409 retry). The insert lives in `_insert_reproduction` so the
  re-check dominates it for `test_visibility_exit_guard`, which cannot see through the unique-clash
  `try`.

## Outcome

- **Actual files:** as planned, plus a private helper in `store.py` (`_cache_version_fills`) and two
  in `routes/scores.py` (`_load_score_to_reproduce`, `_refuse_unless_exact`), because ruff's
  C901 / PLR0912 / PLR0915 limits refused the rule and the route inline. Also
  `.github/workflows/scoreboard-tests.yml` and `.claude/sdlc.local.md` (the new portal test, by
  name). Tests: `tests/unit/test_score_cache_version.py`, `tests/unit/test_score_reproductions.py`,
  `tests/portal/reproduced-count.test.js` (all new, no existing test edited).
- **Commits:** see `git log --oneline e14-a1-scoreboard-metadata..HEAD`.
- **Gates:** `ALL GATES GREEN` (`uv run .claude/scripts/run_gates.py scoreboard --base
  e14-a1-scoreboard-metadata`): append-only check, ruff check, ruff format, pyright, pytest with
  coverage, and the `node --test` gate including `reproduced-count.test.js`. 9 PostgreSQL tests
  skip (none of them new).
- **Coordinator round (2026-10-06):** the three answers above, each with new tests. One of my OWN
  earlier tests (added in this PR, not on the base) changed:
  `test_a_score_never_reproduced_reads_zero_and_no_last_time` is now
  `..._reads_without_either_key`, because the answer reverses what it asserted. Added helper
  `_insert_reproduction` in `store.py`.
- **Design-review round (coordinator, 2026-10-06):** fixes 1-7 and 11 in one round, each behaviour
  change with a new test (the new tests are in my own B4 files). `_load_visible_score` is the one
  shared helper of `_load_owned_score` and the reproduction record (`_load_score_to_reproduce` is
  gone); every answer of the record route carries `PRIVATE_CACHE_HEADERS`; `ReproductionSubmission`
  reuses `ExactScore` (the annotation `ScoreSubmission.score` now also uses, no behaviour change) and
  a `ReproductionClientInfo` that bounds `version` to 64 (the shared `ClientInfo` is untouched);
  the store docstring is corrected and shortened; the 403 is `SUBMIT_SCORE_RESPONSES[403]` and the
  422 documents `CodedErrorResponse | ValidationErrorResponse` (two small doc-only models in
  `schemas.py`); the count fields carry a `description`; the portal drops "· last" for an
  unparseable date. Left as the coordinator said: 8, 9, 10, 12, 13.
- **Deviations:** the private helpers above (accepted); "Reproduced 1 time" for a count of one;
  `uv run` for run_gates.py. The open questions of the first report are answered and applied.
