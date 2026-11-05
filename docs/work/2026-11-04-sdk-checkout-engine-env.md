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

## CI fix (2026-11-05): the replay lane

- **What broke:** the replay lane ran `screamingface prepare --all` in a CI checkout. With this
  PR a checkout builds the editable Engine environment, so `--all` meant all 92 bundles: ten
  minutes of downloads, then a hard stop on `cais/hle` (gated, no token).
- **Fixed in #1673** (merged up): `prepare --all` skips a gated dataset with a warning and a
  count; `prepare` runs `up`'s medxpert-only check.
- **Fixed here:** `prepare` (and `prepare --list`) take the Engine environment `up` takes, so a
  checkout venv without the benchmarks extra falls through to the built one; the bundle list is
  asked once. Pinned by `test_prepare_list_falls_through_like_up` and
  `test_prepare_runs_the_preparer_from_the_environment_up_would_use`.
- **Workflow (owner-approved 2026-11-05):** the replay lane prepares `medxpert` by name, which is
  what `--all` meant before this stack.
- **Evidence:** the lane's prepare step run locally from this worktree, whose Engine venv lacks
  the extra: fell through, built the editable environment, prepared medxpert in 29 s. 238 passed
  across the 13 runtime test files.

## Notebook instructions (2026-11-05)

- **What was stale:** ten notebooks' "Before running" text still described the old layout. Eight
  said the plain `screamingface up` Engine cannot list their Benchmark (`draco`, `ifeval`, both
  HealthBench boards, `gdpval-text`, `contracteval`); notebook 12 said the same of the imported
  boards; notebook 18's local target connected to a second Engine on `:9111`, which the shrunk
  recipe no longer starts, so that notebook was broken locally, not just out of date.
- **Fixed in `scripts/build_notebooks.py`** (the notebooks are regenerated from it): each of
  those notebooks now lists its one-time `screamingface prepare <id>` line above `up`; notebook
  12 explains that the first `up` builds the Engine's inspect environment; notebook 18 targets
  the stack's own Engine on `:9108`. The recipe's now-unused `engine_port` variable is removed.
- **Evidence:** every new `prepare` line run against a fresh data dir with no `HF_TOKEN`:
  draco, ifeval, healthbench-worst30, healthbench-professional, gdpval-text, contracteval,
  inspect-gsm8k all exit 0 (8-41 s each). `check_notebooks.py` clean; 100 passed across the 8
  notebook test files; `just --list` parses.
- **Not changed:** `tests/e2e/workbench/` comments still describe the recipe's old side Engine;
  that harness starts its own Engine and still works, so it is left for its owner.
