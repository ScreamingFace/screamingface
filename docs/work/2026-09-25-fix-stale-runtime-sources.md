---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-25
finished: 2026-09-25
---

# fix-stale-runtime-sources — a dev checkout's local stack always runs the live url4 and apps

## Intent

`just local-stack-notebooks` died at boot with `No module named 'url4.cli._config'`,
while the log claimed "runtime source: checkout". The editable install had vendored a
Sep 18 url4 copy into the dev venv. `import screamingface` loads it before checkout
activation can run, and `verify_live_modules` accepts it because the venv sits inside the
checkout. Stop editable builds from copying (ship a `.pth` to the live sources instead),
and make verification check against the source directories. Spec:
`docs/spec/2026-09-25-fix-stale-runtime-sources.md`.

## Planned changes

- `packages/screamingface/scripts/runtime_build_hook.py`: editable branch writes a `.pth`
- `packages/screamingface/src/screamingface/_runtime/source.py`: `verify_live_modules`
  checks the source dirs and gives a reinstall hint
- `packages/screamingface/pyproject.toml`: `hatchling` dev dep, `[tool.uv] cache-keys`
- `packages/screamingface/uv.lock`: relock
- `packages/screamingface/tests/test_runtime_build_hook.py`: new
- `packages/screamingface/tests/test_runtime_source.py`: append one test

## Test plan

- Editable build: no vendored app/url4 entries, `.pth` lists exactly the four existing
  source dirs.
- Wheel build: still vendors `url4/__init__.py` (don't-regress).
- Verification: a module under `<root>/packages/screamingface/.venv/...` is rejected; the
  message names the module and `--reinstall-package screamingface`.

## Acceptance

- In a synced dev venv, `site-packages/url4` does not exist and `url4.__file__` is under
  `packages/url4/src`.
- `require_runtime_extra()` passes in checkout mode.
- screamingface stack gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. The hook's vendoring moved into `_vendor_runtime` (pure
  code motion) to keep `initialize` under the branch-count lint.
- **Commits:** see the PR. First commit is `fix(screamingface): run the live url4 and apps
  from a dev checkout's editable install`.
- **Gates:** `run_gates.py screamingface`: ALL GATES GREEN (ruff, format, pyright,
  pytest + cov ≥95, notebook check, uv build, distribution check). pytest: 1829 passed,
  26 skipped.
- **Manual acceptance:** after `uv sync` in the worktree venv, `site-packages` holds no
  `url4`/app copies, just `_screamingface_runtime_sources.pth` listing the four live dirs.
  `url4.__file__` resolves to `packages/url4/src` straight after `import screamingface`.
  `require_runtime_extra()` passes. `screamingface up` on spare ports (19105/6/8) came up
  with all three services UP and no `SCREAMINGFACE_RUNTIME_ERROR`, and `down` stopped it.
- **Deviations:** `editables` joined `hatchling` in the dev group. It is hatchling's own
  declared requirement for editable builds (`get_requires_for_build_editable()` →
  `editables~=0.3`), which a real frontend installs automatically. `uv add` also reordered
  unrelated `resolution-markers` and a `zstandard` marker in `uv.lock`. Those hunks were
  restored to main's text, so the lock diff is additions only, and `uv lock --check` passes.
