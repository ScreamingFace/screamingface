---
title: Plan — send the Cloudflare Access login back to the challenged path
spec: docs/spec/2026-10-20-OME-1649-access-login-challenged-path.md
ticket: OME-1649
branch: OME-1649-access-login-challenged-path
created: 2026-10-20
---

# Plan

One unit, one stack (`packages/screamingface`), plus one docs edit.

1. RED. Create `packages/screamingface/tests/test_access_challenged_path.py`:
   - sync: a path-scoped scoreboard mock (`/` 200, `/v1/scores` 302 without a token, 201 with
     it); a replay-safe `POST /v1/scores` through `httpx.Client(auth=...)`. Assert one browser
     URL, `redirect_url` = `https://scoreboard.example/v1/scores` with the same `token` and
     `aud`, and the replayed POST carries `Cf-Access-Token`.
   - async: the same with `httpx.AsyncClient`.
   - `GET /v1/scores/score-1?view=full` → redirect path `/v1/scores/score-1`, no `view` in the
     redirect query.
   - `_access_authorization_url(..., redirect_path="/v1/scores/a%20b")` keeps the encoding.
   - Guard: explicit `login()` keeps the origin path.
   Run the file. The redirect-path tests must fail because the path is empty.
2. GREEN.
   - `_access/contract.py`: add `redirect_path` (keyword-only, default `None`).
   - `_access/auth.py`: add `_challenged_path(url)`. Pass the path from both auth flows through
     `_authenticate_after_redirect` → `_login_after_challenge` → `_interactive_login`.
   Run the new file, then the whole package suite.
3. Docs. Change the ADR 0001 sentence. Add an Unreleased "Fixes" entry to
   `packages/screamingface/CHANGELOG.md`.
4. Gates. `uv run .claude/scripts/run_gates.py screamingface` from the repo root.
5. Ledger outcome. No commit or PR until the user says so. The PR needs the OME-1649
   `docs/tasks` mirror and `Refs: OME-1649`.
