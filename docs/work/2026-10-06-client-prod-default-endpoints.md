---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-06
finished:
---

# client-prod-default-endpoints — Point the Client's default engine + leaderboard at prod

## Intent

The `screamingface` Python Client ships **dev** hosts as its default hosted engine and
leaderboard. Both prod hosts are now live on Cloudflare (DNS verified 2026-10-06:
`leaderboard.screamingface.ai` → 188.114.97.12, `fusion.screamingface.ai` → 188.114.96.12;
`url4.screamingface.ai` does not resolve, so the prod engine host mirrors dev by dropping
`.dev.`). Flip the two shipped defaults so a fresh `sf.Client()` / `sf.connect()` targets
prod. Defaults stay overridable via `SCREAMINGFACE_ENGINE_URL` /
`SCREAMINGFACE_SCOREBOARD_URL`. Scope is deliberately **minimal** (user-confirmed): only the
two defaults plus the tests/snapshot that would otherwise fail — docs site, READMEs, example
notebooks, e2e default, and explicit test-fixture literals are intentionally left on dev.

## Planned changes

- `src/screamingface/client.py:37-38` — `DEFAULT_ENGINE_URL` → `https://fusion.screamingface.ai`,
  `DEFAULT_SCOREBOARD_URL` → `https://leaderboard.screamingface.ai`.
- `tests/test_client_configuration.py:13-14` — assert the two prod defaults.
- `tests/test_public_surface.py:348` — assert `https://fusion.screamingface.ai` for the
  lazily-selected default engine.
- `tests/test_default_client_local_discovery.py:21-22` — `_HOSTED_ENGINE` / `_HOSTED_SCOREBOARD`
  constants → prod hosts.
- `tests/public_surface_snapshot.json` — regenerate (default values embedded in the three
  signatures) via `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`.
- No schema/model change → no migration (S1 N/A).

## Test plan

- **RED first:** update the four assert-the-default tests to expect the prod hosts; they fail
  against the current dev defaults (correct red for the right reason).
- **GREEN:** flip the two constants in `client.py`; new + all prior tests pass.
- Snapshot tripwire (`test_public_surface.py`) regenerated deliberately, then re-run green.
- Invariant protected: a fresh default Client/`sf.connect()` with no env override and no
  explicit URL points at the hosted **prod** engine + leaderboard.

## Acceptance

- `python -c "import screamingface as sf; c=sf.Client(); print(c.engine_url, c.scoreboard_url)"`
  prints the two prod hosts.
- `run_gates.py screamingface` fully green (ruff, format, pyright, pytest ≥95% cov, notebooks,
  build, distribution).
- `public_surface_snapshot.json` diff shows only the two host changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** exactly as planned —
  `src/screamingface/client.py` (2 constants), `tests/test_client_configuration.py`,
  `tests/test_public_surface.py`, `tests/test_default_client_local_discovery.py`,
  `tests/public_surface_snapshot.json` (regenerated). No `_ui/cards.py`, docs, examples,
  README, or e2e change (minimal scope held). No schema change → no migration (S1 N/A).
- **Commits:** not yet committed — paused at the append-only Confidence Gate (see below).
- **Gates:** `run_gates.py screamingface --skip-append-only` → **ALL GATES GREEN** (ruff,
  format, pyright, pytest `-n auto` 2239 passed / 26 skipped / 96.23% cov ≥95%, notebooks,
  build, distribution). Env note: a fresh worktree needs `uv sync --extra notebook` before
  pyright (CI's install step), else `ipywidgets` import-resolution fails — unrelated to this
  change. One xdist flake (`test_client_run.py::test_concurrent_interrupt_deletes_every_active_engine_capability`,
  passes 3/3 in isolation, uses an explicit engine_url — not this change) cleared on re-run.
- **Deviations:** the append-only gate (sdlc rule 5) flags the 4 modified prior-test
  artifacts. These are the deliberate, user-approved contract change (default endpoints
  dev→prod). PAUSED here per the Confidence Gate: needs owner approval recorded via
  `.claude/test-change-approvals/OME-N.json` (byte-exact blob transitions, keyed to the
  Linear issue + branch), which is created at PR-open once OME-N is filed under an epic.
