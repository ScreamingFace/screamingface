---
ticket: OME-1001
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1001 — Start the local stack with one command for devs and users

## Intent

Make `screamingface up` the only way to start the local stack. Today devs run
`just stack-up` (per-app venvs, justfile env exports) while users run the CLI's
bundled runtime — two build paths, so a user-path bug (missing dependency pin,
GitHub `#735`) never breaks a dev machine. After this unit the CLI detects a repo
checkout and serves the live `apps/` + `packages/url4` code (dev mode), serves the
installed package elsewhere, carries the justfile's env defaults itself, and the
justfile is deleted.

## Planned changes

- NEW `packages/screamingface/src/screamingface/_runtime/source.py` — runtime-source
  resolution: marker-based checkout detection (never "a folder named apps/ exists"),
  `SCREAMINGFACE_RUNTIME_SOURCE=checkout|bundled` override, sys.path activation for
  live checkout code, PYTHONPATH entries for child processes.
- `packages/screamingface/src/screamingface/_runtime/server.py` — activate the
  resolved source before importing runtime apps (`require_runtime_extra`,
  `run_scoreboard`); log the chosen mode at boot.
- `packages/screamingface/src/screamingface/_runtime/bootstrap.py` — justfile env
  defaults move here: `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1`,
  `AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES={"openrouter": 32}` (OME-889), keeping
  the existing setdefault semantics (explicit operator choice wins).
- `packages/screamingface/src/screamingface/_runtime/cli.py` — record the runtime
  source in the state document; refuse to adopt a healthy running stack owned by a
  different checkout/source; extend `_prepare`'s child env with checkout PYTHONPATH.
- DELETE `packages/screamingface/justfile`.
- `packages/screamingface/tests/e2e/…` — replace `just stack-prepare`/`just stack-up`
  wording in docstrings and skip hints with the `screamingface` CLI equivalents.

## Test plan

- source resolution: full marker set present → checkout; any marker missing → bundled;
  env var forces each mode; forcing checkout without markers is an error; invalid env
  value is an error.
- activation: prepends exactly the four live src dirs ahead of site-packages;
  idempotent on repeat calls.
- bootstrap defaults: new env defaults applied; explicit operator values survive
  (extends the existing OpenRouter test).
- `_up` adoption guard: same-source healthy stack adopts as before; different-checkout
  state refuses with a `screamingface down` hint; legacy state without a source key
  still adopts.
- state document: `_serve_logged` writes the resolved source.

## Acceptance

- Inside the repo, `screamingface up` serves the live checkout code and logs
  `runtime source: checkout (<root>)`; outside, bundled mode is logged.
- Gateway/scoreboard migrations still run on first boot with a fresh data dir
  (existing `_migrate` path — verified, unchanged).
- A second checkout cannot silently adopt the first checkout's running stack.
- The OME-889 concurrency override and provider bootstrap survive the justfile's
  deletion.
- `packages/screamingface/justfile` is gone; no live doc/test references `just`
  stack commands (engine-side justfile guard test self-skips; flagged for follow-up).
- Full screamingface gate suite green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — NEW `_runtime/source.py` + `tests/test_runtime_source.py`;
  modified `_runtime/{cli,server,bootstrap}.py`, `tests/test_runtime_cli.py`,
  `tests/e2e/{harness/stack.py,harness/_local_proc.py,test_boards.py,test_failures.py}`;
  deleted `packages/screamingface/justfile`. No notebook/README/`.claude/README.md`
  changes were needed — verified none reference `just` stack commands (the ticket's
  step-5 list was broader than reality).
- **Commits:** `feat: serve the live checkout from screamingface up and retire the justfile`
  (single commit on `OME-1001-one-command-stack`; sha in the Linear close comment).
- **Gates:** run_gates.py screamingface ALL GREEN — ruff check, ruff format, pyright,
  pytest 1176 passed / 17 skipped (cov ≥95%), check_notebooks, uv build,
  check_distribution. Append-only check acknowledged via `--skip-append-only` (see
  Deviations). Live smoke test: fresh data dir boot on ports 19105/19106/19108 —
  `runtime source: checkout (<worktree>)` logged, apps served from the live worktree
  paths, both SQLite DBs migrated on first boot, foreign-source adoption refused with
  the `screamingface down` hint, same-source re-up adopted, `down` clean.
- **Deviations:**
  - Three prior tests edited (append-only rule 5, ticket-mandated, invariants kept):
    `test_runtime_cli.py` — `enable_local_providers` exact-dict assert relaxed to
    key asserts because step 4 grows the default set (its invariant, explicit choice
    survives, still asserted); `tests/e2e/test_boards.py` / `test_failures.py` —
    skip-hint strings named the deleted `just stack-prepare` command, now
    `screamingface prepare`. Skip conditions untouched.
  - Engine-side justfile guards left alone (out of this landing): the justfile-reading
    engine test self-skips now that the file is gone, and
    `screamingface-engine-tests.yml` still lists the deleted justfile in its `paths:`
    filters (harmless dead entries). Follow-up ticket proposed at close to retire both.

## Review response (same unit, second commit)

Owner-run code review returned 9 findings; fixes applied on the branch:

- **Provider credential bootstrap is no longer defaulted at all** (owner decision,
  supersedes the plan's "move all justfile env defaults"): the gateway documents
  `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` as consent/opt-in, so the runtime never sets
  it — an operator exports it themselves. Dev consequence: a restarted gateway boots
  with an empty profile index until re-authorized. Tests pin the flag's absence.
- Adoption guard now runs on every owned branch of `up` AND in `restart` — the
  partially-healthy path advised `restart`, which would have silently torn down
  another checkout's stack.
- `down`/`logs` skip runtime-source resolution: a typoed `SCREAMINGFACE_RUNTIME_SOURCE`
  must never lock the user out of recovery (mirrors the recovery-port rule).
- `activate()` enforces sys.path precedence (an editable .pth can hold a source dir
  BEHIND site-packages), and `verify_live_modules` fails boot loudly if checkout mode
  imported any stale installed copy.
- e2e assets default now derives from the runtime data dir (where
  `screamingface prepare` writes); the old `/tmp` default had no remaining filler.
- `public-docs` leaderboard guide: `just stack-up` → `screamingface up`.
- Engine (cross-landing fallout, mechanical): deleted the two dead justfile guard
  tests, removed the workflow's dead justfile `paths:` entries, scrubbed the word
  from test text (owner instruction). Engine gate suite green.
- Rejected with reasoning (in PR discussion): adoption-identity granularity
  (bundled↔bundled adoption equals pre-existing behavior), port-scan teardown
  fallback (real gap, needs a portability design — follow-up candidate),
  `SCREAMINGFACE_ENGINE_REPO` stacked-dev override (dead workflow, intentional drop).
- Verified: both gate suites green (`screamingface` 1181 passed / 17 skipped ≥95% cov;
  `screamingface-engine` all green); fresh-dir boot logs checkout mode with live-module
  verification active; foreign-source `up` refused on healthy AND partial stacks;
  clean `down`.
