---
ticket: OME-1620
stack: screamingface
status: done
started: 2026-11-04
finished: 2026-11-04
---

# sdk-engine-child-process — `screamingface up` starts the Engine from an Engine environment

## Intent

A pip user's `screamingface up` serves medxpert only: the 87 imported boards live in a plugin
that needs `inspect-ai`, which cannot share an env with the runtime extra's litellm pin
(OME-1626), and the wheel's vendored Engine source carries no entry-point metadata anyway. This
unit lets `up` start the Engine as a CHILD PROCESS from an Engine environment of its own —
`SCREAMINGFACE_ENGINE_PYTHON`, or, in a checkout, the Engine app's own `.venv` — and routes
`prepare` through the Engine's own preparer, so a dev's `up` serves every board and the local
Scoreboard seeds from the running Engine over HTTP exactly like the hosted one. With no Engine
environment the stack boots as today (in-process Engine, medxpert). PR 2 of 3; PR 3 builds the
environment for pip users and retires the in-process path.

## Planned changes

- `src/screamingface/_runtime/engine_env.py` (new): resolve the Engine interpreter, list its
  bundles, refuse a medxpert-only env, build the serve/prepare commands, bundle status rule.
- `src/screamingface/_runtime/config.py`: `RuntimeConfig.engine_python`.
- `src/screamingface/_runtime/cli.py`: `--engine-python` on up/restart/prepare/_serve; `_config`
  resolves it; `_up` probes the env and prints it; state records it; `prepare` uses the Engine's
  preparer (`--root`, `--bundle`, `--list-bundles`) when an Engine env is set; `status`/`doctor`
  read bundle folders by the cases.json rule in that mode; `--seed-from-engine` on `_scoreboard`.
- `src/screamingface/_runtime/server.py`: Engine child process (relayed into runtime.log),
  Scoreboard started after the Engine is healthy and seeded over HTTP; in-process path unchanged.
- `tests/test_runtime_engine_env.py` (new). No prior test touched.

## Test plan

- Interpreter resolution: flag > env var > checkout default > None; a named path that is not a
  file is refused by name.
- Bundle listing parses the preparer's `--list-bundles` output; a failing child surfaces its
  stderr and the remediation; a medxpert-only env is refused with the `uv sync` line.
- Commands: serve child = `-m screamingface_engine.cli serve --local --port N`; prepare child =
  `-m screamingface_engine.benchmarks.prepare --root <assets> --bundle <id>`; the child env
  carries `URL4_BENCHMARK_ASSETS`, `URL4_CLOUD_AIGATEWAY_BASE_URL`, the artifacts dir.
- Bundle status: missing / incomplete (no or unparseable or empty cases.json) / prepared.
- `prepare` in Engine mode: unknown id refused naming `--list`; `--force` clears the folder first;
  `--list` prints every bundle id with its status.
- Scoreboard: `run_scoreboard(..., seed_from_engine=True)` seeds with `engine_url`, no rows.
- `_build_apps` builds no in-process Engine when `engine_python` is set; still does otherwise.

## Acceptance

- New tests pass; `test_runtime_cli.py`, `test_runtime_benchmark_assets_dir.py`,
  `test_runtime_artifacts_dir.py`, `test_runtime_uvicorn_log_surfaces.py` stay green unmodified;
  ruff + pyright clean on touched files.
- Manual (owner): from a checkout with the Engine venv synced with `--extra benchmarks`,
  `screamingface up` prints the Engine env and board count; `screamingface prepare --list`
  shows every bundle; `sf.benchmarks.list()` on the local Engine returns them.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `engine_env.py` (new), `config.py`, `cli.py`, `server.py`,
  `tests/test_runtime_engine_env.py` (27 tests, new), both READMEs.
- **Commits:** see PR.
- **Gates:** `uv run --isolated pytest` on the 9 runtime test files (`test_runtime_engine_env.py`,
  `test_runtime_cli.py`, `test_runtime_benchmark_assets_dir.py`, `test_runtime_artifacts_dir.py`,
  `test_runtime_uvicorn_log_surfaces.py`, `test_runtime_artifact_status.py`,
  `test_runtime_source.py`, `test_runtime_extra_parity.py`,
  `test_default_client_local_discovery.py`) → 185 passed, no prior test touched; ruff check +
  format clean; pyright 0 errors on the touched files. Relevant tests only (owner rule).
  **Real boot (2026-11-04, outside judge):** `screamingface up --foreground` from this worktree
  with `SCREAMINGFACE_ENGINE_PYTHON` = the Engine app's venv (synced with `--extra benchmarks`) on
  ports 9205/9206/9208 against the owner's prepared datasets: all three `/healthz` 200, the
  Engine's `/v1/benchmarks` lists 89 Benchmarks, the Scoreboard's lists the same 89 (seeded over
  HTTP), clean shutdown exit 0; `prepare --list` prints 92 bundles in 3.9 s; `prepare nope` is
  refused naming `--list`. Script: scratchpad `smoke/run.sh` (not committed).
- **Deviations:** two bugs the real boot caught that the unit tests had not: (1) the venv's
  `bin/python` symlink was resolved into the base interpreter (no packages) — now kept as the
  symlink, pinned by `test_a_venv_symlink_is_kept_as_the_venv_interpreter`; (2) the child was
  started with `-m screamingface_engine.cli`, which has no `__main__` guard and exits 0 at once —
  now an explicit `main()` entry, pinned in the serve-command test. A dead child's output is
  drained into runtime.log before "stopped during startup" is raised, so the next such failure
  names its cause.

## Review round 1 (2026-11-05)

- **Blocker fixed:** prior runtime tests depended on the developer's real Engine venv (a prior
  restart test failed with "serves only medxpert" on a box whose venv lacks the extra; spawned a
  4 s child on one that has it; CI green only because CI has none). The checkout-default rung is
  now one function, `engine_env.checkout_engine_venv`, and an autouse conftest fixture hides the
  REAL checkout's venv (fake checkouts under tmp_path keep theirs) and unsets
  `SCREAMINGFACE_ENGINE_PYTHON`. Pinned by
  `test_a_restart_in_this_checkout_never_runs_the_real_engine_venv`, which makes the real
  checkout look like it has a venv; removing the fixture turns it red (mutation run).
- **Nonblocking fixed:** the Scoreboard child exits when seeding from the Engine fails (no empty
  board behind READY); `status` reads bundle folders on disk and never starts the Engine;
  `doctor` reports a broken Engine environment as FAIL instead of dying; `restart` keeps the
  recorded interpreter over a merely-found default; `prepare` uses the running stack's
  interpreter unless one is named; the Engine child runs in its own session and a child that
  ignores terminate is killed after 10 s; the banner says "benchmark bundles".
- **Left, noted in the PR:** a SIGKILLed supervisor still orphans its children (true of the
  Scoreboard child before this PR too); `restart` probes the Engine twice; the medxpert-only
  refusal names the one hand-built bundle.
- **Gates:** 194 passed across the 9 runtime test files (9 new); ruff + pyright clean.
