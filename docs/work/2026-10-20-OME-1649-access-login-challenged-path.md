---
ticket: OME-1649   # issue exists (filed from the Slack thread); not filed by this unit
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-20
finished: 2026-10-20
---

# access-login-challenged-path — send the Access login back to the challenged path

## Intent

`sf.leaderboards.submit()` cannot publish to `leaderboard.screamingface.ai` (OME-1649). In
staging and production the leaderboard has its own Cloudflare Access application that covers
only `/v1/scores` and its subpaths; `/` is public. After a challenge, the SDK browser login sets
`redirect_url` to the origin root. Access does not run on `/`, so the edge never transfers the
application token, the browser lands on the public dashboard, and the SDK polls until the 300 s
timeout. Infra keeps the two Access applications (Stephen, OME-1649 thread, 2026-10-20), so the
SDK must redirect to the path that Access challenged. This unit also corrects the ADR 0001
sentence that says the hosted deployment uses one shared Access application.

Spec: `docs/spec/2026-10-20-OME-1649-access-login-challenged-path.md`.
Plan: `docs/plan/2026-10-20-OME-1649-access-login-challenged-path.md`.

## Planned changes

- `packages/screamingface/src/screamingface/_access/contract.py`: `_access_authorization_url`
  takes an optional keyword `redirect_path`; when given it replaces the origin path in
  `redirect_url`.
- `packages/screamingface/src/screamingface/_access/auth.py`: the sync and async challenge
  flows pass the challenged request path (encoded, without the query) through
  `_authenticate_after_redirect` → `_login_after_challenge` → `_interactive_login`.
  `login()` keeps the origin path.
- `packages/screamingface/tests/test_access_challenged_path.py` (new).
- `packages/screamingface/CHANGELOG.md`, if the package keeps one for unreleased fixes.
- `docs/adr/0001-keep-caller-authentication-origin-scoped.md`: replace the shared-application
  sentence.

## Test plan

- RED, sync: path-scoped app (`/` → 200, `POST /v1/scores` without token → 302). A replay-safe
  POST logs in once; the browser `redirect_url` is `https://<scoreboard>/v1/scores?...` with the
  same transfer `token` and `aud`; the replayed POST carries `Cf-Access-Token` and gets 201.
- RED, async: the same through `httpx.AsyncClient`.
- RED: a challenged `GET /v1/scores/score-1?view=full` redirects to `/v1/scores/score-1`; the
  original query is not copied.
- RED: `_access_authorization_url(..., redirect_path=...)` keeps a percent-encoded path as is.
- Guard (passes before and after): explicit `login()` on a whole-host origin keeps the origin
  path in `redirect_url`.
- All prior tests stay unchanged and green, including
  `test_authorization_url_preserves_engine_path_without_existing_query`.

## Acceptance

- After a reactive challenge, the authorization URL's `redirect_url` path equals the challenged
  request path on the configured origin's host.
- `login()` and every whole-host flow are unchanged.
- ADR 0001 no longer claims one shared hosted Access application.
- `run_gates.py screamingface` is green.
- Live check (outside this unit, needs a human browser): one staging submit, then one
  production submit, reported on OME-1649.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_access/contract.py` (`redirect_path` keyword),
  `_access/auth.py` (`_challenged_path` helper; the path flows through
  `_authenticate_after_redirect` → `_login_after_challenge` → `_interactive_login`),
  `tests/test_access_challenged_path.py` (new, 5 tests), `CHANGELOG.md` (Unreleased Fixes),
  ADR 0001. Spec and plan in `docs/spec/` and `docs/plan/`.
- **RED:** 4 tests failed for the right reason (redirect path `''`; no `redirect_path`
  keyword); the `login()` guard passed before and after.
- **Commits:** `fix(screamingface): return the Cloudflare Access login to the challenged path`
  (one commit on `OME-1649-access-login-challenged-path`, squash-merged through the PR).
  Scope confirmed by the user: RC-1 only; RC-2 stays out.
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN (ruff, format, pyright, pytest
  `-n auto` with 95 % coverage floor, notebooks, build, distribution check);
  `run_gates.py repo` ALL GATES GREEN. Prior tests unchanged.
- **Deviations:** the venv needs `uv sync --extra notebook` (as CI does) for pyright, not
  only `--dev`. `_access/auth.py` was 692 lines before this unit (over the 450-line target);
  this unit adds about 25 and does not split it. Live staging and production submits are
  still open and need a human browser login.
