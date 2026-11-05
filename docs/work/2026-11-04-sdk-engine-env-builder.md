---
ticket: OME-1620
stack: screamingface
status: done
started: 2026-11-04
finished: 2026-11-04
---

# sdk-engine-env-builder — `screamingface up` builds the Engine environment for pip users

## Intent

PR 2 lets `up` start the Engine from an Engine environment it is pointed at; a pip user has
none. This unit makes `up` BUILD one on first run, from material the wheel already carries
plus the Engine's pinned dependency world, so `pip install screamingface[runtime]` then
`screamingface up` serves every board — the same pins as the deployed Engine, so revisions
match and local results stay publishable. No PyPI publishing of the Engine: the wheel vendors the
Engine's project file and its inspect plugin beside the sources it already ships, and the
environment is assembled from those at build time. PR 3 of 3 (OME-1620 / OME-1626).

## Planned changes

- `scripts/runtime_build_hook.py`: vendor `screamingface_engine_inspect`, the Engine's
  `pyproject.toml`, url4's `pyproject.toml` + `README.md` + `LICENSE` (hatchling needs them).
- `src/screamingface/_runtime/resources/engine-requirements.txt` (committed): the Engine's
  `benchmarks` world exported from its lock; `scripts/export_engine_requirements.py` regenerates it
  and a test fails on drift.
- `src/screamingface/_runtime/engine_env.py`: `existing_engine_environment`,
  `ensure_engine_environment` (key = pins + project files + Python minor; uv if on PATH, else
  venv + pip; old keys removed; half-built dirs never reused), `_assemble_projects`.
- `src/screamingface/_runtime/cli.py`: `up`/`restart`/`prepare` build the environment in bundled
  mode when none is set; `status`/`doctor` find a built one; `doctor` names the Engine env.
- `scripts/check_distribution.py`: the new wheel material is required.
- `tests/test_runtime_engine_env_builder.py`, `tests/test_runtime_build_hook_engine_dist.py`
  (new). No prior test touched.
- `README.md` (SDK): the pip flow.

## Test plan

- Key: changes with the pins; a ready environment is reused with no command run.
- Build: uv sequence (`uv venv --python <this python>`, `uv pip install -r pins`, `uv pip install
  --no-deps <url4> <engine>`); pip fallback sequence; assembled project dirs hold the project
  file and `src/<package>`; the ready marker lands last; a failing step names itself and leaves
  no half-built folder; another key's folder is removed.
- Resolution: a built environment under the data dir is the fourth rung; bundled `up` builds
  when none is set, checkout `up` does not.
- Drift: the committed requirements equal a fresh export of the Engine lock.
- Wheel: the release wheel carries the plugin, both project files and the pins; the editable wheel
  carries none of them.

## Acceptance

- New tests pass; the PR 2 test files and `test_runtime_build_hook.py` stay green unmodified;
  ruff + pyright clean on touched files.
- Outside judge: build the wheel, install it with `[runtime]` into a fresh venv OUTSIDE the
  checkout, run `screamingface up` → the environment builds, the Engine lists the imported
  boards; `prepare ifeval` runs the Engine's preparer.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/conftest.py` (an autouse guard so no test ever
  builds a real environment, with `real_engine_build` to opt back in) and the frozen-app guard
  in `engine_env.environment_for_pip_install`.
- **Commits:** see PR.
- **Gates:** `uv run --isolated pytest` on the 12 runtime test files (the 9 of PR 2 plus
  `test_runtime_engine_env_builder.py`, `test_runtime_build_hook_engine_dist.py`,
  `test_runtime_build_hook.py`) → 206 passed, no prior test touched; ruff check + format clean;
  pyright 0 errors on the touched files. Relevant tests only (owner rule).
  **Outside judge (2026-11-04):** `uv build` of this branch (wheel 3.8 MB), `check_distribution`
  OK, `uv pip install "<wheel>[runtime]"` into a fresh venv OUTSIDE the checkout, then
  `screamingface up --foreground` on ports 9305/9306/9308 against the owner's prepared datasets:
  the environment built under the data dir (556 MB, uv on PATH with a warm cache: the whole
  build + boot finished within the minute), all three `/healthz` 200, the Engine's
  `/v1/benchmarks` lists 89, the Scoreboard's the same 89, `doctor` reports `PASS engine
  environment`, `prepare --list` reuses the environment, clean shutdown exit 0. Script:
  scratchpad `smoke3/run.sh` (not committed).
- **Deviations:** the ready marker is written after a `mkdir` so a replaced installer in tests
  cannot fail the marker step; the build moved to after adoption and the port check in `up` (a
  stack already running needs no environment; a 700 MB build must never precede a refusal) —
  the plan had it before the probe only.

## Review round 1 (2026-11-05)

- **Blocker fixed — frozen Studio crashed at config time.** Looking for a built environment ran
  on every `up`/`status`/`doctor` and computed the environment key, which raises with no
  `engine_dist/` and no checkout. `existing_engine_environment` now never raises (frozen → none;
  no key → none); only a build raises. Pinned by
  `test_looking_for_a_built_environment_never_raises_without_project_files` (frozen and not).
- **Blocker fixed — the drift test could not run when the drift happened.** The SDK lane does
  not trigger on the Engine's lock. Instead of a workflow edit (CI is owner territory), an
  Engine-lane twin, `apps/screamingface-engine/tests/unit/test_sdk_engine_requirements_conformance.py`,
  reads the SDK's pins and the export script's flags as text (like the inspect pin twin) and
  compares pin sets with a fresh export. Mutation run: bumping one committed pin turns it red.
  Both copies now compare pin SETS, so a uv formatting change cannot fail an unrelated PR.
- **Nonblocking fixed:** the build call in `up` is pinned by
  `test_up_hands_the_built_environment_to_the_stack` (deleting the call turns it red, mutation
  run); two `up`s serialize on `engine-env/.build.lock` and the second reuses the first's build
  (`test_two_ups_never_build_over_each_other`); the build prints `1/3 … 2/3 … 3/3` so a pip
  install no longer looks hung; the key test also perturbs the project files; `doctor` keeps one
  engine-environment check after the merge of PR 2.
- **OME-1626 stays open** (re-scoped in Linear): the two extras still cannot co-install; this
  stack only removes the need for Benchmarks.
- **Gates:** 221 passed across the 12 runtime test files; the Engine twin passes; ruff + pyright
  clean on the touched files of both apps.
