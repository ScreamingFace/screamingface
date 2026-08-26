---
ticket: OME-998
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-998 — Connect to the running local stack by default instead of the hosted engine

## Intent

`sf.connect()` (and every module-level convenience call) builds the lazy default Client
against the hosted engine even while `screamingface up`'s local stack is running, so local
testers stall at "waiting / Authorize" unless they already know the
`SCREAMINGFACE_ENGINE_URL` export. This unit teaches the default client to discover a
**running** (liveness-checked) local runtime from the state `screamingface up` writes and
prefer it, with explicit env vars keeping absolute precedence and hosted staying the
silent fallback.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/detect.py` (new) —
  `running_local_services()`: read `runtime.json` from the data dir, validate via the same
  schema check `screamingface status` uses (`_state_services`), gate on a real engine
  `/healthz` probe; return the services map or `None`. Never raises.
- `packages/screamingface/src/screamingface/_runtime/config.py` — hoist the
  `"runtime.json"` filename into a module constant so detect and `RuntimeConfig.state_path`
  cannot drift.
- `packages/screamingface/src/screamingface/_default_client.py` — precedence when building
  the lazy default client: env var → discovered running local stack (announced with an
  info line naming the URL and the override env var) → hosted default (silent, as today).
- `packages/screamingface/tests/test_default_client_local_discovery.py` (new).
- `packages/screamingface/tests/test_public_surface.py` — make the two prior lazy-default
  tests hermetic (point `SCREAMINGFACE_DATA_DIR` at an empty tmp dir) so they keep
  asserting the "no local state → hosted" contract on machines that have a live stack.

## Test plan

- Happy path: no env var + valid state + live engine `/healthz` (real ephemeral HTTP
  server) → client uses the local engine and scoreboard URLs; info message printed once.
- Precedence: `SCREAMINGFACE_ENGINE_URL` set while a "running" local stack exists → env
  value wins, discovery not consulted.
- Stale state: state file present but engine port dead (real refused connection) → hosted
  default, no message. INVARIANT: a crashed runtime never routes connect at a dead port.
- No state file / malformed JSON / wrong `schema_version` → hosted default, no probe.
- `configure(...)` explicit args unaffected by discovery.

## Acceptance

- `screamingface up` + fresh notebook + `sf.connect()` → panel targets the local engine,
  terminal names the chosen URL and the override env var.
- All prior tests green and unmodified in what they assert; gates for the `screamingface`
  stack green (ruff, format, pyright, pytest ≥95% cov, notebooks, build, distribution).

## Decisions

- When discovery wins, BOTH `engine_url` and `scoreboard_url` come from the discovered
  services (each env var individually retains precedence). WHY: `screamingface up` tells
  users to export both; auto-switching only the engine would invent a hybrid state
  (local engine + hosted leaderboard) the documented flow never produces. Flagged for
  review in the PR.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except `tests/test_public_surface.py` was NOT modified —
  hermeticity landed as a new autouse fixture in `tests/conftest.py` (new file) that
  points `SCREAMINGFACE_DATA_DIR` at an empty tmp dir suite-wide, keeping prior tests
  append-only (the repo gate enforces this mechanically) while removing the whole
  suite's dependence on the developer's real `~/.screamingface`.
- **Commits:** b5f760d6 — feat(screamingface): connect to a running local stack by default
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN (append-only check, ruff check,
  ruff format, pyright, pytest ≥95% cov incl. 12 new tests, notebooks, build,
  distribution).
- **Deviations:** the planned edit to the prior lazy-default test was replaced by the
  conftest fixture above. The scoreboard-follows-discovery decision stands as planned
  and is flagged for owner review in the PR.
