---
ticket: OME-994
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-994 — Ship the missing dependencies so a fresh install works first try

## Intent

Community GitHub issue #735: on a clean machine,
`pip install "screamingface[runtime,notebook]"` then `screamingface up` dies with
`Form data requires "python-multipart" to be installed`. The wheel bundles the
gateway app, whose own pyproject declares `python-multipart`, but the client's
`[runtime]` extra — the thing pip actually resolves — omits it. Second half of
the report: the Installation docs claim the `[notebook]` extra pulls jupyterlab;
the extra deliberately stays minimal (INVARIANT in pyproject), so the docs
sentence is the bug, not the extra.

## Planned changes

- `packages/screamingface/pyproject.toml` — add `python-multipart>=0.0.20` to the
  `[runtime]` extra (mirrors the gateway's own pin).
- `packages/screamingface/tests/test_runtime_extra_parity.py` — NEW invariant
  test: every direct dependency of the three bundled runtime apps is resolvable
  from the client's base deps + `[runtime]` extra, with an explicit allowlist for
  names satisfied transitively (pydantic, asyncpg) and vendored code (url4).
- `public-docs/src/pages/sf-client/InstallationPage.vue` — stop promising
  jupyterlab in the `[notebook]` extra sentence.
- `docs/tasks/2026-08-26-OME-994-client-extras-missing-deps.md` — mirror
  committed with the work.

## Test plan

- RED: parity test fails on today's pyproject naming exactly `python-multipart`
  as missing from the runtime extra.
- GREEN: adding the dep turns it green; full screamingface suite stays green.
- Invariant protected: a bundled app can never again grow a direct dependency
  that the installable extra silently drops (#735 bug class).

## Acceptance

- `screamingface[runtime]` resolves `python-multipart` (extra declares it).
- Parity test red-flags any future drift between bundled apps' deps and the extra.
- Installation docs no longer promise jupyterlab from `[notebook]`.
- All screamingface stack gates green; PR opened referencing OME-994 / GH #735.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `packages/screamingface/pyproject.toml`,
  `packages/screamingface/tests/test_runtime_extra_parity.py` (new),
  `public-docs/src/pages/sf-client/InstallationPage.vue`, the docs/tasks mirror,
  this ledger.
- **Commits:** single commit on `OME-994-runtime-multipart` (squash-merged via PR;
  sha recorded in the Linear close comment).
- **Gates:** `run_gates.py screamingface` ALL GREEN (ruff, format, pyright,
  pytest cov≥95, notebooks, uv build, distribution). public-docs lane: prettier
  --check, oxlint, eslint, `npm run build` all clean (no test suite there).
- **Deviations:** jupyterlab was NOT added to `[notebook]` — the extra carries an
  INVARIANT keeping it panel-only; the docs sentence was the bug and was fixed
  instead. RED confirmed before the fix: parity test named exactly
  `python-multipart` missing.
