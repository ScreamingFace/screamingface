---
ticket: OME-1594
stack: client-sf
status: done
started: 2026-10-13
finished: 2026-10-13
---

# bump-jupyter-server — JupyterLab loads again in the SDK dev environment

## Intent

JupyterLab in the SDK's dev environment opens to a blank page. Dependabot moved tornado to 6.5.9
(`1dfed1971`). Its static-file handler now reads `allowed_symlink_directory`, which tornado's own
`initialize` sets. jupyter-server 2.20.0's `FileFindHandler` replaces that `initialize` and never
sets it, so every static file returns 500 with an `AttributeError`. jupyter-server 2.21.1 sets the
attribute itself, so the fix is to upgrade that one package in the lock.

## Planned changes

- `packages/screamingface/uv.lock`: `uv lock --upgrade-package jupyter-server` (2.20.0 → 2.21.1).

## Test plan

- No unit test: the break lives in a third-party pair of locked versions, and the SDK suite never
  starts a notebook server. Instead, a manual smoke check: start `jupyter lab` from the bumped lock
  and fetch its `main.*.js` bundle and the favicon.

## Acceptance

- `main.*.js` and `/static/favicons/favicon.ico` return 200, and the server log has no
  `allowed_symlink_directory` traceback.
- The lock diff touches jupyter-server only.

## Outcome

- **Actual files:** `packages/screamingface/uv.lock` (3 lines) plus this ledger and the
  `docs/tasks` mirror, as planned.
- **Commits:** see PR.
- **Gates:** manual smoke check: `main.c9147cb24d83fa64.js` 200, favicon 200, 0 tracebacks
  (tornado 6.5.9 + jupyter-server 2.21.1). `uv tree --invert --package jupyter-server --no-dev` is
  empty: only the `dev` group pulls it in, so nothing published changes. CI and the pre-push hook
  run the SDK suite.
- **Deviations:** none.
