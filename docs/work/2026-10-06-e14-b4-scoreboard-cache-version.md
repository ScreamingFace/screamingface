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

## Frozen-copy rework (2026-10-08)

The owner changed the E14 design on 2026-10-08. The cache version is gone. A run now captures a
frozen copy in the AI Gateway. This PR changes the names, the copy-id check and the texts only.
Spec: `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` section 6.
Plan: `docs/plan/2026-10-06-e14-reproducible-submission/F-B4-scoreboard-frozen-copy.md`.

### What changed

- `cache_revision` is now `frozen_copy_id`. It is a UUID string: `CharField(36, null=True)`. The schema
  type `FrozenCopyId` checks it with `uuid.UUID` and stores `str(uuid)` (lower case, with hyphens).
  The old pattern `cr-<12 hex>` is no longer valid. An upper-case UUID is stored in lower case.
- `reproducible` is now `capture_status`: `Literal["complete", "partial"] | None`, `CharField(16,
  null=True)`. The schema type `ReproducibleStatus` is now `CaptureStatus`.
- `score_reproductions.cache_revision` is now `score_reproductions.frozen_copy_id`.
- Rule I1: `frozen_copy_id` needs `capture_status`. The error text is `frozen_copy_id requires
  capture_status`.
- The fill-only rule is unchanged. `frozen_copy_id` and `capture_status` fill together, gated on a
  NULL `capture_status`. `answer_seed` fills alone. The helper is now `_frozen_copy_fills`.
- `POST /v1/scores/{id}/reproductions` is unchanged except for the names. It answers 409
  `not_reproducible` when `capture_status` is not `complete`. It answers 422 `not_exact` when
  `score`, `total_questions` or `frozen_copy_id` differ.
- Migration `0020_score_cache_version.py` is now `0020_score_frozen_copy.py`, rewritten in place. It
  was never released: the E14 stack is local and no deployed database has it. `makemigrations`
  reports "No changes detected".
- Docstrings, comments, OpenAPI descriptions and the 409 message are updated. The message is now
  "only a score whose run was fully captured can be reproduced".
- The portal needs no change. `portal/spec.js` reads `reproduction_count` and `last_reproduced_at`
  only.

### Tests

Only this PR's own tests changed: `tests/unit/test_score_cache_version.py` and
`tests/unit/test_score_reproductions.py`. Both are new in this PR. No test from before this PR is
edited. The file names stay, to keep the branch history easy to follow.

- Renamed fields, constants (`COPY_ID`, `OTHER_COPY_ID`, UUID values), test names and comments.
- `BAD_FIELDS`: the bad-label cases are now bad-UUID cases. Upper-case hex is no longer a bad
  value, because it is normalised.
- New: `test_a_copy_id_is_stored_in_lower_case_canonical_form`,
  `test_a_copy_id_in_upper_case_is_the_same_copy`, and a `VARCHAR(36)` check in the migration test.

### Pinned-decision notes

- `uuid.UUID` also accepts the forms without hyphens, with braces and with `urn:uuid:`. The schema
  accepts them and stores the canonical form. The spec says "validate with `uuid.UUID`, store
  `str(uuid)`", so this is by design. No test pins the non-hyphen forms.
- The branch name and this ledger file name keep "cache-version". The plan says to rework in place.

## Rebase onto main (2026-10-08)

- The stack was rebased onto `origin/main` `4cd063445` (87 new commits on main).
- Conflict in `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml`: both lists keep
  main's portal test files and add `tests/portal/reproduced-count.test.js`.
- Gates for stack `scoreboard` pass against `e14-a1-scoreboard-metadata`.
