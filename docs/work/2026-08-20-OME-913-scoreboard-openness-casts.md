---
ticket: OME-913
stack: scoreboard
status: done
started: 2026-08-20
finished: 2026-08-20
---

# OME-913 — Cast Tortoise CharField reads at the Openness Literal boundaries

## Intent

Dependabot PR #637 (`scoreboard-python-minor`) is red on `test (3.13)` solely because
`tortoise-orm 1.1.7 → 1.1.8` gives `fields.CharField(...)` a real `str | None` type where
pyright previously inferred `Any`. `openness_override` then no longer satisfies the
`Literal["open","closed"] | None` parameter it feeds. Landing the casts on main first lets
Dependabot deliver the bump unmodified via `@dependabot rebase`.

## Planned changes

- `src/scoreboard/scores/store.py` — cast at the `openness_override=` schema argument.
- `src/scoreboard/scores/baseline_store.py` — same.
- No model, schema or migration change (S1 does not apply — nothing about the DB shape moves).

## Test plan

**Deviation from literal RED/GREEN, stated up front:** `typing.cast` is erased at runtime, so
no runtime test can distinguish before from after. The failing signal that demands this change
is the `uv run pyright` gate under tortoise-orm 1.1.8, and that is what is used as RED:

- RED: pin `tortoise-orm[asyncpg]==1.1.8`, run `uv run pyright` → 2 `reportArgumentType`
  errors at the two sites above.
- GREEN: same command, 0 errors, with the casts in place.
- Regression: revert the pin to 1.1.7 and re-run pyright → still 0 errors, proving the casts
  are safe to land ahead of the bump.
- The full existing suite must stay green and unmodified.

## Acceptance

- `uv run pyright` clean under BOTH tortoise-orm 1.1.7 and 1.1.8.
- All scoreboard gates green; no prior test touched.
- Committed diff contains the casts ONLY — no dependency change (that stays Dependabot's).

## Outcome

- **Actual files:** as planned — `src/scoreboard/scores/store.py`,
  `src/scoreboard/scores/baseline_store.py`. No model/schema/migration change.
- **Commits:** see below.
- **Gates:** `run_gates.py scoreboard` — ALL GATES GREEN (append-only check, ruff check,
  ruff format --check, pyright, pytest --cov-fail-under=80, portal node tests).
- **RED/GREEN evidence:**
  - RED under `tortoise-orm==1.1.8`: 2 × `reportArgumentType` at `baseline_store.py:27`
    and `store.py:72`.
  - GREEN under 1.1.8 with the casts: `0 errors, 0 warnings, 0 informations`.
  - Regression under 1.1.7 with the casts: `0 errors` — confirms the casts land safely
    ahead of the bump.
- **Deviations:**
  - The line number in the issue was `store.py:65`; the real site is `:72` — main moved
    during the Dependabot sweep before this branch was cut. No behavioural difference.
  - No runtime test was added. `typing.cast` is erased at runtime, so no test can
    distinguish before from after; the `pyright` gate under 1.1.8 is the failing signal
    that demanded the change, and it is recorded above. Flagged rather than papered over
    with a test that would assert nothing.
  - Imported `Openness` from `scoreboard.classification.openness` (runtime import, matching
    the existing precedent at `scores/frontier.py:9`) rather than inlining a `Literal`.
    Safe: `classification` imports `scores.schemas` only under `TYPE_CHECKING`, so there is
    no import cycle.
