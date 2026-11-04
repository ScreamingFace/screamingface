---
ticket: OME-1620
stack: screamingface
status: done
started: 2026-11-04
finished: 2026-11-04
---

# sdk-checkout-engine-env — a checkout's `up` builds its Engine environment too; `just` shrinks

## Intent

After PR 3 a pip user's `up` builds the Engine environment, but a dev in a checkout still has
one manual step: `uv sync --extra benchmarks` in the Engine app, which `up` only hints at — and
that sync puts the inspect extra into the dev's own venv, which breaks the pre-push gate. This
unit makes a checkout `up` build the SAME sidecar environment, with the live Engine and url4
installed editable, under the data dir: nothing to run by hand, the dev's venv untouched, edits
served live. The Engine app's venv is still used when it exists and is full. With that, the
`just local-stack-notebooks` recipe loses its Engine half and becomes three commands
(`prepare --all`, `up`, `jupyter lab`). Two hints ride along: `up` says when no dataset is
prepared yet, and `prepare --all` warns instead of failing when a gated dataset was skipped
for lack of a Hugging Face token. PR 4 of 4 (OME-1620).

## Planned changes

- `src/screamingface/_runtime/engine_env.py`: `ensure_engine_environment(..., editable_root=)`
  (key carries the root; install step `--no-deps -e <root>/packages/url4 -e
  <root>/apps/screamingface-engine`); `environment_for(data_dir, source, environ)` replaces
  `environment_for_pip_install` (bundled → wheel copies; checkout → editable; frozen → None).
- `src/screamingface/_runtime/cli.py`: in a checkout, an Engine app venv that lists medxpert
  only falls through to the built environment instead of refusing (a NAMED interpreter is still
  refused); `up` prints the no-datasets hint; `prepare` warns on a zero-exit preparer that wrote
  no cases.json.
- `justfile`: `local-stack-notebooks` = prepare --all, up, jupyter lab; teardown kept.
- `tests/test_runtime_checkout_engine_env.py` (new). No prior test touched.
- `README.md` (SDK), the mirror's PR list.

## Test plan

- Editable key differs from the wheel key and carries the root; the editable install sequence
  (uv and pip) names both projects with `-e` and no `_assemble_projects` call.
- `environment_for`: checkout → editable build under the data dir; bundled → wheel build;
  frozen → None.
- `up`: a checkout default venv listing medxpert only → built environment used and said so; a
  named interpreter listing medxpert only → refused as before.
- The no-datasets hint prints when no bundle is prepared, not otherwise.
- A zero-exit preparer that wrote no cases.json → warning, no raise; non-zero → raise.

## Acceptance

- New tests pass; the PR 2/3 test files stay green unmodified; ruff + pyright clean.
- Outside judge: from this worktree (no Engine venv in it), `screamingface up` builds the
  editable environment and serves the imported Benchmarks.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`engine_env.py`, `cli.py`, `justfile`, SDK `README.md`, the new
  test file, the mirror), plus two PR 3 tests adjusted on purpose (see Deviations).
- **Commits:** see PR.
- **Gates:** `uv run --isolated pytest` on the 13 runtime test files → 216 passed; ruff check +
  format clean; pyright 0 errors on the touched files. `just --list` parses.
  **Outside judge (2026-11-04):** `screamingface up --foreground` from THIS worktree, which has
  no Engine venv: the editable environment built under the data dir (547 MB) and the stack was
  ready in 18 s; all three `/healthz` 200; the Engine lists 89 Benchmarks; inside the built env
  the Engine and url4 modules resolve to the worktree's live sources; clean shutdown exit 0.
  Script: scratchpad `smoke4/run.sh` (not committed).
- **Deviations:** two tests from the still-open PR 3 (#1674) changed meaning with this PR and
  were edited rather than left to fail: `test_up_builds_the_environment_for_a_pip_install_only`
  now expects a checkout to build (editable) instead of keeping in-process, and
  `test_a_frozen_app_never_builds` calls the renamed `environment_for`. Both are this stack's own
  unmerged tests; flagged here and in the PR body for the reviewer. `test-paid-benchmarks` in
  the justfile keeps its own sync-and-prepare loop (a paid-run recipe; out of scope).
