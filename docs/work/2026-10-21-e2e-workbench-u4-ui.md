---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-10-21
finished:
---

# e2e-workbench-u4-ui — local web UI for the e2e workbench: bundle viewer + run launcher

## Intent

Unit 4 of the e2e notebook workbench (epic OME-1636, spec
`docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.5, plan
`docs/plan/2026-10-17-e2e-workbench-u4-ui.md`). A developer opens a loopback-only page, picks
a target (`replay` | `local`) and notebooks, starts the same pytest lane CI runs, watches its
output live, and reads every evidence bundle (verdict, trace chain, log excerpts, executed
notebook, cost) without opening files by hand. Owner decisions 2026-10-17: dev-only under
`tests/e2e/workbench/ui/` (never in the SDK wheel; no `screamingface workbench` CLI), and the
first version is viewer + launcher only; hosted/preview targets and Access login wait for unit 3.

## Planned changes

- `docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.5 — dev-only location, owner decisions,
  security constraints (Task 1)
- `packages/screamingface/pyproject.toml` + `uv.lock` — `nbconvert>=7.16` in the `dev` group
  (Task 1)
- `packages/screamingface/tests/e2e/workbench/ui/`:
  - `__init__.py`, `test_ui_skeleton.py` (Task 1)
  - `bundles.py` + `test_bundles.py` — discover/load bundles, path-confined (Task 2)
  - `render.py` + `test_render.py` — executed notebook → empty-sandbox iframe (Task 3)
  - `runs.py` + `test_runs.py` — one pytest run at a time, streamed, group-cancelled (Task 4)
  - `app.py`, `__main__.py` + `test_app.py` — routes, Host/token/CSP guards, pages (Task 5)
  - `test_ui_e2e.py` — real replay run through the UI (Task 6)
- `packages/screamingface/justfile` — `workbench-ui` recipe (Task 6)
- `packages/screamingface/tests/e2e/workbench/README.md` — "UI" section (Task 6)

## Test plan

- Task 1: nbconvert importable in the dev env and declared directly in the `dev` group (not
  only transitively, not in `runtime`).
- Bundles: newest-first discovery of local and run-scoped bundles; malformed/missing
  `trace.json` listed as unreadable; traversal keys and symlinked dirs never read.
- Render: full HTML document; iframe with `sandbox=""` and escaped `srcdoc`.
- Runs: env/argv built from the request; paid gate (`confirm_paid` + `OPENROUTER_API_KEY`);
  stem validation; streaming + exit code; 409 while busy; cancel kills the process group; a
  crashing run ends with its exit code.
- App: wrong `Host` → 400; POST without token → 403 and no spawn; with token → 303 + SSE
  stream; 409/400; bundle page shows hops, escaped logs, sandboxed notebook; traversal → 404;
  CSP and `X-Frame-Options: DENY` on every response; malformed bundle shows as unreadable.
- E2E (gated like the replay lane): a real `replay` run for `quickstart` through the UI ends
  with returncode 0, its bundle is listed PASS, both hops found, iframe present.

## Acceptance

- Tasks 1–6 committed; gates green (`pytest`, `ruff check`, `ruff format --check`, `pyright`).
- UI e2e test passes on replay.
- Manual smoke (plan Task 6 Step 3) recorded here, including ports 9105/9106/9108 free after a
  mid-run cancel.
- At PR-open: one `cross-unit/repo-dev-processes` leaf under OME-1636.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <counts>
- **Deviations:**
  - Task 1: `nbconvert` was already importable in the dev env (transitively via
    `jupyterlab`), so the plan's import test passes before the change. RED came from an added
    test asserting `nbconvert` is a direct `dev`-group dependency and absent from `runtime`.
  - Task 6: the entry point is fixed by `PYTHONPATH` in the `just workbench-ui` recipe, not by
    `__main__` — `python -m workbench.ui` imports the package before `__main__` runs, so a
    `sys.path` insert there can never take effect. The recipe uses `source_directory()` (a
    first draft with `justfile_directory()` broke `just screamingface workbench-ui` from the
    repo root; caught RED by the repo-root case of `test_entrypoint.py`). It also takes
    `*args` (passed to the module, e.g. `--port`, `--no-open`), beyond the plan's `out` only.
  - Task 6: added `ui/test_entrypoint.py` (not in the plan's file list): boots
    `python -m workbench.ui` and `just workbench-ui` (package dir + repo root) for real and
    fetches the page; the `just` cases skip where `just` is not on PATH (CI today). Locally
    `just` 1.59.0 came from `uvx --from rust-just`.
  - Task 6: the e2e test passes the child an environment without `OPENROUTER_API_KEY` /
    `SCREAMINGFACE_TEST_PAID`, so a stray export can never make it a paid run.

## Manual smoke (plan Task 6 Step 3) — 2026-10-21

Started with `just screamingface workbench-ui <scratch out> --no-open` (repo root, `just` via
uvx; `OPENROUTER_API_KEY` unset). The Playwright browser was held by another session, so the
page's own requests were driven with an httpx script against the live server instead of a
browser; the iframe was checked in HTML, not visually.

- Index 200 with the token; `Host: evil.example:9112` → 400; POST `/runs` without token → 403.
- Replay run for `quickstart`: 303 to the run page (EventSource present); the SSE stream
  delivered pytest output from +0.2 s, 21 lines, ending `{"returncode": 0, "cancelled": false}`.
- Index row for `runs/<id>/replay/quickstart` carries the PASS pill; bundle page: two `found`
  hops, candidates table, `<iframe class="nb" sandbox="">` present.
- Second run (all notebooks): a third POST while it ran → 409; cancel after ~4 s → 303, stream
  ended `{"returncode": 2, "cancelled": true}`.
- Afterwards `lsof -iTCP:9105 -iTCP:9106 -iTCP:9108 -sTCP:LISTEN` empty; no testcontainers
  left running. SIGINT to the UI exited it; 9112 free too. Note: replay does not bind
  9105/9106/9108 at all — the port check after a cancelled `local` run needs a paid run and was
  not done.

## Post-review polish — 2026-10-21

Rebased onto the core branch (redaction.py, verdict.py, exact trace ids, allowlisted local
env, JUnit); the workbench unit and UI suites were green as-is, no rebase fix needed.

- Runs select `test_notebooks.py::test_notebook[<target>-<stem>]` node ids, not `-k`.
- A replay child never gets `OPENROUTER_API_KEY` (or `SCREAMINGFACE_TEST_PAID`).
- `--basetemp=<run out>/pytest-tmp`, so a local run's runtime data dir is known. A cancel that
  needed SIGKILL, or any cancelled local run, shows "the runtime may still be up" and the exact
  `screamingface down --data-dir …`; cancelling a finished run → 409 "already finished —
  nothing to cancel".
- UI shutdown: the lifespan hook was skipped on uvicorn's force exit (second Ctrl-C) and SIGHUP
  killed the UI outright, leaving the run going (RED in the new `ui/test_shutdown.py`). Now
  `main` cancels the run after serving, a further signal SIGKILLs its group, SIGHUP → SIGTERM.
- Run page: `running <notebook>… mm:ss` from pytest's `collected` line to each result (server-
  derived, SSE `progress` event; `log_cli` stays off).
- quickstart `WORKBENCH_RESULT` carries `cost_usd`; unknown money is null (it was the string
  "None" for `cache_saved_cost_usd`). Bundle page: Spend column + total, unknown → "unknown".
- README: `up` is not in the run's process group (only `down` stops it); start command and a
  5-step human test checklist.

Verified: workbench unit + UI suites; `SCREAMINGFACE_TEST_E2E=1` keyless runs of
`ui/test_ui_e2e.py` (real replay through the UI) and `test_cancelling_a_local_boot_frees_its_ports`;
a scripted smoke of the real UI on :9112 (progress `running quickstart… 00:06`, PASS, 409 on a
finished cancel, spend `$0` with cache-saved `unknown`, Ctrl-C mid-run → UI exit 130, no
pytest left, 9105/9106/9108/9112 free). Not run: a paid `local` run.

## Follow-ups found in the final smoke (2026-10-21)

- **Cancel during replay-stack boot can orphan the Postgres testcontainer briefly.** `replay_stack`
  (`tests/e2e/harness/stack.py`) calls `backend.start()` outside its `try`, and
  `CacheSeededGateway` assigns `self._container` only after `container.start()` returns, so an
  interrupt mid-boot skips `backend.stop()`. Testcontainers' Ryuk reaper removes the container once
  the run's process exits (verified: none left afterwards), so the leak is transient. The proper fix
  lives in the shared harness (core branch, pre-existing file); it needs its own test-change
  approval, so it's tracked separately rather than reopening PR #1455.
- No paid `local` run yet: the cancel guidance for a real local runtime and real `cost_usd`
  rendering are verified only with fakes and on replay.
- `just` is not installed on the dev machine; the documented no-`just` command was smoked instead.
