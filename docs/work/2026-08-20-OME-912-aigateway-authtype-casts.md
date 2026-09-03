---
ticket: OME-912
stack: aigateway
status: done
started: 2026-08-20
finished: 2026-08-20
---

# OME-912 — Cast Tortoise CharField reads at the AuthType Literal boundaries

## Intent

Dependabot PR #640 (`aigateway-python-minor`) is red on `test (3.13)` solely because
`tortoise-orm 1.1.7 → 1.1.8` gives `fields.CharField(...)` a real `str` type where pyright
previously inferred `Any`, so values read off a model no longer satisfy `AuthType`
(`Literal["oauth","api_key"]`). Landing the casts on main first lets Dependabot deliver the
bump unmodified via `@dependabot rebase`. Sibling of OME-913 (scoreboard); split per D9
because one issue may carry only one landing leaf.

## Planned changes

- `src/aigateway/core/oauth/store.py` — cast at the `auth_type=` argument (~line 377).
- `src/aigateway/routes/chat_credentials.py` — cast at the `AuthType` return (~line 46).
- One further site, to be enumerated from the gate run (the log tail showed "3 errors" but
  truncated the third).
- No model, schema or migration change (S1 does not apply).

## Test plan

**Deviation from literal RED/GREEN, stated up front:** `typing.cast` is erased at runtime, so
no runtime test can distinguish before from after. The failing signal that demands the change
is the `uv run pyright` gate under tortoise-orm 1.1.8, and that is used as RED:

- RED: pin `tortoise-orm[asyncpg]==1.1.8`, run `uv run pyright` → the 3 `reportArgumentType` /
  `reportReturnType` errors.
- GREEN: same command, 0 errors, with the casts in place.
- Regression: revert the pin to 1.1.7, re-run pyright → still 0 errors, proving the casts are
  safe to land ahead of the bump.
- Full existing suite green and unmodified.

## Acceptance

- `uv run pyright` clean under BOTH tortoise-orm 1.1.7 and 1.1.8.
- All aigateway gates green; no prior test touched.
- Committed diff contains the casts ONLY — no dependency change.

## Outcome

- **Actual files:** as planned — `src/aigateway/core/oauth/store.py`,
  `src/aigateway/routes/chat_credentials.py`. No model/schema/migration change.
- **Commits:** see below.
- **Gates:** `run_gates.py aigateway` — ALL GATES GREEN (append-only check, ruff check,
  ruff format --check, pyright, check_no_enterprise, pytest --cov-fail-under=80).
- **RED/GREEN evidence:**
  - RED under `tortoise-orm==1.1.8`: 3 errors — `store.py:376` (status),
    `store.py:377` (auth_type), `chat_credentials.py:46` (return).
  - GREEN under 1.1.8 with the casts: `0 errors, 0 warnings, 0 informations`.
  - Regression under 1.1.7 with the casts: `0 errors`.
- **Deviations:**
  - The third site was NOT a second `AuthType` boundary as the issue guessed. It is
    `status=connection.status` at `store.py:376`, a *different* Literal alias
    (`OAuthConnectionStatus = Literal["pending","active","expired","revoked","error"]`,
    `core/oauth/schemas.py:13`). Same root cause, second alias — so the fix imports two
    aliases, not one. Issue description updated to match.
  - `AuthType` lives in `aigateway.core.profile_models` (not `core/oauth/schemas.py`, which
    merely re-imports it).
  - No runtime test added: `typing.cast` is erased at runtime, so no test can distinguish
    before from after. The `pyright` gate under 1.1.8 is the failing signal that demanded the
    change and is recorded above — flagged rather than papered over with a vacuous test.
