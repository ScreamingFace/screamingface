---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-06
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
