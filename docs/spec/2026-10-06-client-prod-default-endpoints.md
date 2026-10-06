# Point the Client's default engine + leaderboard at prod

Status: owner-approved · Stack: screamingface · Epic: OME-1304 (E11 · Production release)

## Problem

The `screamingface` Python Client ships **dev** hosts as its default hosted engine and
leaderboard:

- `DEFAULT_ENGINE_URL = "https://fusion.dev.screamingface.ai"`
- `DEFAULT_SCOREBOARD_URL = "https://leaderboard.dev.screamingface.ai"`

Both prod hosts are now live on Cloudflare (DNS verified 2026-10-06:
`fusion.screamingface.ai` → 188.114.96.12, `leaderboard.screamingface.ai` → 188.114.97.12).
E11 (OME-1304) names this explicitly: *"Requires also pinning client to prod instead of
\*.dev.\*"*. A fresh `sf.Client()` / `sf.connect()` should target prod, not dev.

## Decisions

### D1 — Flip the two shipped defaults to the bare prod hosts

`https://fusion.dev.screamingface.ai` → `https://fusion.screamingface.ai` and
`https://leaderboard.dev.screamingface.ai` → `https://leaderboard.screamingface.ai`. The prod
engine host mirrors the dev one by dropping `.dev.` — `url4.screamingface.ai` (the engine's
cloud Helm hostname) does **not** resolve and is not the SDK target.

### D2 — Defaults stay overridable; nothing else in the contract changes

The env overrides `SCREAMINGFACE_ENGINE_URL` / `SCREAMINGFACE_SCOREBOARD_URL`
(`_default_client.py`) still win. The public-surface snapshot moves (the signature default
values), which is the intended, reviewable change.

### D3 — Minimal scope (user-confirmed)

Only the two defaults plus the tests/snapshot that assert them. Docs site, READMEs, example
notebooks, the e2e default, and explicit test-fixture literals are deliberately **left on
dev** in this unit — a later unit may sweep them.

### D4 — No deployment/infra change

DNS, ingress, and Cloudflare Access are owned by the platform team and already live. This unit
only changes where the client points.
