---
ticket: OME-1555
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-09
finished: 2026-10-09
---

# runtime-benchmark-assets-dir — runtime `--benchmark-assets-dir` (Slice D1)

## Intent

Studio ships every benchmark dataset inside the signed app (spec decision D10) and needs the
local runtime to read them from that read-only folder instead of `<data-dir>/benchmark-assets`.
`screamingface up` gains `--benchmark-assets-dir PATH`; the Engine receives it as
`URL4_BENCHMARK_ASSETS`, `status`/`doctor` report bundle status from it, and `prepare` keeps
writing to the data directory (it refuses the option). The default behaviour is unchanged.

Approved inputs (landing with the slice A PR, `studio-compose-fusion-run` branch):

- Spec: `docs/spec/2026-10-01-studio-compose-fusion-run.md` — D10 and §4.4 "D1"
- Plan: `docs/plan/2026-10-09-studio-compose-fusion-run.md` — §"Slice D1" (T-D1.1, T-D1.2)

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/config.py` — `RuntimeConfig.benchmark_assets_dir: Path | None = None`, resolved in `__post_init__`; `assets_dir` returns it when set.
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `--benchmark-assets-dir` on `up`, `restart` and the internal `_serve`; `prepare` refuses it; `up` fails fast on a missing folder; the serving child records the folder in `runtime.json` (PR #1217 has not merged, so the existing state pattern is used); `status --json` and `doctor` read the recorded folder from an owned state.
- `packages/screamingface/tests/test_runtime_benchmark_assets_dir.py` — new test module (`test_runtime_cli.py` is already ~1000 lines).
- `packages/screamingface/CHANGELOG.md`, `packages/screamingface/README.md`.

## Test plan

- Config: default `assets_dir` unchanged; override resolves `~` and relative paths and is absolute.
- CLI parse: `screamingface --data-dir D up --benchmark-assets-dir P` parses; `_config` carries it.
- `_build_apps` passes the override as `URL4_BENCHMARK_ASSETS` to `create_local_app`.
- `doctor` lists all six bundles prepared from a fixture folder recorded in owned state, and names the folder.
- `status --json` reports the recorded folder; default state output gains no new key.
- `prepare --benchmark-assets-dir` exits non-zero with a clear message.
- `up` with a missing folder fails before any service starts, with the path in the error.
- The background `_serve` child command carries the option; the state record carries it only when set.
- `restart` keeps the recorded folder when the option is not repeated.

## Acceptance

- All card gates for stack `screamingface` green; default behaviour byte-for-byte unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_runtime/config.py`, `_runtime/cli.py`,
  `tests/test_runtime_benchmark_assets_dir.py` (21 tests), `CHANGELOG.md`, `README.md`.
  `server.py` needed no change: it already passes `config.assets_dir` as `URL4_BENCHMARK_ASSETS`.
- **Commits:** `18cf76c26` — feat(screamingface): read benchmark datasets from --benchmark-assets-dir
- **Gates:** `run_gates.py screamingface` — ALL GATES GREEN (append-only, ruff check, ruff
  format, pyright, pytest 2317 passed / 26 skipped at 96.25% coverage, notebooks, uv build,
  check_distribution).
- **Final CLI shape:** `screamingface [--data-dir D] up [--foreground] [--benchmark-assets-dir P]`
  — the option goes after `up` (it is per-command; `--data-dir` stays accepted before or after).
- **Deviations:**
  - PR #1217 had not merged (still open), so the folder is recorded in `runtime.json` as
    `benchmark_assets_dir`, the existing state pattern; the key is absent by default.
  - `restart` also takes the option and otherwise keeps the recorded folder (as it keeps
    ports) — not in the plan, added so a restart never silently drops the bundle.
  - `status --json` gains a `benchmark_assets_dir` key and `doctor` a `benchmark assets dir`
    line only when the override is in effect, keeping default output byte-for-byte unchanged.
  - Open: `up` adopting an already-running healthy stack does not compare that stack's recorded
    folder with a new `--benchmark-assets-dir` (ports are not compared either).

## Rebase onto main (2026-10-20, PR #1328 merge conflicts)

- **Conflicts:**
  - `CHANGELOG.md`: kept main's new entries and put this entry back in its original place.
  - `_runtime/cli.py` status JSON: #1217 merged with `artifacts_*` keys. Kept both those keys and this PR's `benchmarks` (from the effective folder) and `benchmark_assets_dir`. #1217 also records its folder in `runtime.json` state, the same pattern this PR uses, so nothing else changed.
- **Main changed what `prepare` covers.** Five benchmarks are now local inspect Tasks (`5dff3a366`…`2d04f7810`), and `cli._BENCHMARKS` is `("medxpert",)`. This PR's tests hardcoded the old six-bundle list, so they now use `cli._BENCHMARKS`. No assertion was weakened.
- **Gates:** ruff, format and pyright are clean. 4217 passed and 33 skipped, with 97.02% coverage. Notebooks pass.

## Review follow-up (2026-10-20, PR #1328: keelancj, HupBaHa)

- **Restart checks the folder before stopping the stack.** `_restart` resolves the requested or recorded folder, then calls `_require_benchmark_assets_dir` before `_down`. A missing path, a file, or a recorded folder that disappeared now leaves the running stack untouched.
  - New test: `test_restart_checks_the_folder_before_stopping_the_runtime[missing|file|missing-recorded]`. It failed first, with `_down` called.
  - The existing restart test now creates its folders, because restart checks them.
- **`up` no longer adopts a healthy stack serving a different folder.** With an explicit `--benchmark-assets-dir`, an owned healthy stack is adopted only if it serves exactly that folder. Otherwise `up` refuses with `run screamingface restart --benchmark-assets-dir <path>`. That includes a stack serving the data directory.
  - New test: `test_up_refuses_a_healthy_runtime_serving_another_folder[other|None]`, which failed first.
  - Guard test: `test_up_adopts_a_healthy_runtime_serving_the_same_folder`.
- **Merged-tree test:** `test_status_json_reports_artifacts_and_the_recorded_folder_together` asserts the artifact status (#1217) and the recorded datasets folder in one response. It is a guard; the rebase had already put both together.
- **Not done (the reviewer marked it as a follow-up):** `doctor` failing rather than passing when a recorded folder is missing or unreadable, and tightening how stale state feeds remembered config.
- **Gates:** ruff, format and pyright are clean. 4224 passed and 33 skipped, with 97.02% coverage. Notebooks pass.
