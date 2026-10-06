# Plan — Point the Client's default engine + leaderboard at prod

Spec: docs/spec/2026-10-06-client-prod-default-endpoints.md · Epic: OME-1304

## Change (single source of truth)

`packages/screamingface/src/screamingface/client.py` — `DEFAULT_ENGINE_URL` and
`DEFAULT_SCOREBOARD_URL` to the bare prod hosts. These two constants feed every default
(`Client`/`AsyncClient` signatures, `_default_client.py` fallbacks).

## Lockstep test updates (fail the moment the defaults change)

- `tests/test_client_configuration.py` — the default-client host assertions.
- `tests/test_public_surface.py` — the lazily-selected default-engine assertion.
- `tests/test_default_client_local_discovery.py` — the `_HOSTED_ENGINE` / `_HOSTED_SCOREBOARD`
  constants (used across that file's default-host assertions).
- `tests/public_surface_snapshot.json` — regenerated via
  `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (embeds the default
  values in the three signatures).

These four are prior tests; editing them is a deliberate contract change (append-only gate,
sdlc rule 5) recorded via an owner-approved `.claude/test-change-approvals/OME-N.json`.

## TDD

RED: update the four default-assertion tests to expect prod → they fail against the still-dev
default. GREEN: flip the two constants → new + all prior tests pass. Regenerate the snapshot.

## Verification

- `uv sync --extra notebook` (CI install step — provides ipywidgets for pyright) then
  `uv run .claude/scripts/run_gates.py screamingface` fully green.
- `python -c "import screamingface as sf; c=sf.Client(); print(c.engine_url, c.scoreboard_url)"`
  prints the two prod hosts.
