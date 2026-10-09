---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-09
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
