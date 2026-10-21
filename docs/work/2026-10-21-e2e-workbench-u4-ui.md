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
