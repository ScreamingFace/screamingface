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
