---
ticket: OME-1650
stack: scoreboard
status: done
started: 2026-10-18
finished: 2026-10-18
---

# fix-public-score-read-access-gate — anonymous score read outside the Access path

## Intent

Production Cloudflare Access gates every `/v1/scores` subpath and every method. The portal spec
page reads `GET /v1/scores/{id}` as an anonymous visitor, gets a 302, and silently hides the
copy-url4 button, paper link, metadata-edited line and reproduced count. A reproducible url4 is
the core promise of the leaderboard. We add `GET /v1/public/scores/{id}`: the same body, one
shared implementation, identity never read, private-board scores always the OME-894 404. The
portal calls it. Code only; no Cloudflare change.

Spec: `docs/spec/2026-10-18-fix-public-score-read-access-gate.md`.
Plan: `docs/plan/2026-10-18-fix-public-score-read-access-gate.md`.

## Evidence (2026-10-18, live, anonymous curl)

- `GET /v1/scores/x`, `/v1/scores/`, `/V1/scores/x`, `/v1//scores/x` -> 302 to Access login.
- `GET /v1/scoresx`, `/v1/scores-public/x`, `/v1/public/scores/x`, `/v1/leaderboard/x/y/history`
  -> 404 from the app (not gated). Access matches whole path segments.

## Planned changes

- `apps/scoreboard/src/scoreboard/routes/scores.py`: extract `_read_score`; `get_score` calls
  it; add `get_public_score` at `/v1/public/scores/{score_id}` (identity None).
- `apps/scoreboard/src/scoreboard/scores/schemas.py`: description text names both paths.
- `apps/scoreboard/portal/spec.js`: fetch the public path; header comment.
- `apps/scoreboard/tests/unit/test_public_score_read.py`: new.
- `apps/scoreboard/tests/portal/reproduced-count.test.js`, `paper-link.test.js`: stub key, path test.
- `apps/scoreboard/README.md`, `apps/scoreboard/DEPLOYMENT.md`: one note each.

## Test plan

- Python (new file): public 200 anonymous; body parity with canonical; no private headers on
  200; reproduction count carried; unknown id 404 with private headers; private score 404
  anonymous; owner identity ignored (404 on alias, 200 on canonical); refusal identical to
  unknown (body and headers); turned-private 404; 503 on store error; 422 on non-UUID; 405 on
  POST/PATCH; OpenAPI documents the path.
- Portal: spec page requests `/v1/public/scores/<id>` and no `/v1/scores*` path; existing
  paper-link and reproduced-count tests pass with the new stub key.

## Acceptance

- AC1-AC6 in the spec, section 6.

## Decisions

- Option A (public alias, identity ignored) chosen over history-DTO extension, a `latest`
  object, an identity-reading alias, a path move, a Cloudflare change and a forced login.
- No SDK change: `Scoreboard.get_score` keeps the gated path for verified private-board owners.

## Open (non-blocking)

- Path name `/v1/public/scores/{id}` is the planner's choice; the owner can rename before code.
- Later unit: let anonymous SDK reads use the public alias.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/scoreboard/src/scoreboard/routes/scores.py`: `_read_score` extracted; `get_score` delegates; `get_public_score` added at `/v1/public/scores/{score_id}`; module docstring sentence.
  - `apps/scoreboard/src/scoreboard/scores/schemas.py`: description text names both paths.
  - `apps/scoreboard/portal/spec.js`: fetches `/v1/public/scores/`; header comment.
  - `apps/scoreboard/tests/unit/test_public_score_read.py`: new, 13 tests.
  - `apps/scoreboard/tests/portal/reproduced-count.test.js`: public key, request log, path test.
  - `apps/scoreboard/tests/portal/paper-link.test.js`: public key.
  - `apps/scoreboard/tests/unit/guards/test_visibility_exit_guard.py`: allowlist key `get_score` -> `_read_score`, comment.
  - `apps/scoreboard/README.md`, `apps/scoreboard/DEPLOYMENT.md`: one note each.
  - `docs/spec/`, `docs/plan/`, `docs/work/` (this ledger): 2026-10-18 fix-public-score-read-access-gate.
- **Commits:** `e003f254a` fix(scoreboard): serve anonymous score reads from /v1/public/scores; plus a docs commit filing OME-1650 (ledger + `docs/tasks` mirror). Branch renamed to `OME-1650-public-score-read` at PR-open.
- **Gates:** all run from `apps/scoreboard` after the review round 2 fix:
  - `uv run ruff check`: exit 0, no findings.
  - `uv run ruff format --check`: exit 0, 153 files already formatted.
  - `uv run pyright`: exit 0, 0 errors, 0 warnings.
  - `uv run pytest --cov=scoreboard --cov-fail-under=80 -q`: exit 0, 1200 passed, 9 skipped, 3 deselected; coverage 90.49%.
  - `node --test` (12 named portal files): exit 0, 137 tests, 137 pass, 0 fail.
  - `tests/unit/guards/test_visibility_exit_guard.py`: 4 passed.
- **Deviations:**
  - Review round 2 (blocking, approved by the review findings): `tests/unit/guards/test_visibility_exit_guard.py` was edited although spec AC5 named only the two portal stubs. The `get_score` `Raise` exits (404 unknown id, 404 private refusal, 503 store down) moved into `_read_score`, so the guard allowlist key was stale and `_read_score` was reported as an unguarded function. Fix: key renamed to `("scores.py::_read_score", "Raise"): 3`, same count and reason; RESTRICTIVE comment renamed to `_read_score`. No assertion weakened. Spec AC5 should name this guard file as a second permitted change.
