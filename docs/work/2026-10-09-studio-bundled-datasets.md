---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: studio shell (apps/screamingface-studio src-tauri + runtime; not on the sdlc card, gates per the plan)
status: done
started: 2026-10-09
finished: 2026-10-09
---

# studio-bundled-datasets — Studio bundles all benchmark datasets and points the runtime at them

Slice D2 of the Studio compose-and-run spec (`docs/spec/2026-10-01-studio-compose-fusion-run.md`,
D10 and §4.4; plan `docs/plan/2026-10-09-studio-compose-fusion-run.md` §"Slice D2"). The spec and
plan land with slice A's PR. Stacked on `runtime-benchmark-assets-dir` (slice D1), which gives
`screamingface up` the `--benchmark-assets-dir` option.

## Intent

On a fresh install every run failed with `benchmark_unavailable`: the Engine reads datasets from
disk and only the CLI's `prepare` downloads them. The owner chose to ship all six bundles (eight
benchmarks) inside the installer. The Studio build prepares them once into a build cache, copies
them into the Tauri resources, and the shell passes the bundled folder to `up`.

## Planned changes

- `apps/screamingface-studio/src-tauri/before_build.sh`: after the sidecar is built and signed,
  run `prepare --all` into `runtime/build/benchmark-data` (`HF_TOKEN` passed through), fail unless
  `--list` reports all six `prepared`, then `rsync -a --delete` the bundles into
  `src-tauri/resources/screamingface-runtime/benchmark-assets/`.
- `apps/screamingface-studio/src-tauri/tests/before_build_test.sh` (new): plain bash harness that
  stubs the sidecar binary and the other build steps.
- `apps/screamingface-studio/src-tauri/src/runtime_process.rs`: a pure `sidecar_args` function;
  `--benchmark-assets-dir <resource_dir>/screamingface-runtime/benchmark-assets` only when that
  folder exists.
- `apps/screamingface-studio/runtime/verify-sidecar.sh`: `/v1/benchmarks` lists 8 rows; a 1-case
  run per bundle (except DRACO) completes case loading and ends `succeeded` with a null score.
- `apps/screamingface-studio/runtime/README.md`: document the bundled datasets.

## Test plan

- Shell: a stubbed `--list` with one bundle `missing` makes the script exit non-zero and copies
  nothing; all `prepared` copies the bundles and exits 0.
- Rust: the argument is present (path built from the resource dir) when the folder exists, and
  absent when it is missing; base args unchanged.
- `verify-sidecar.sh` against the real frozen sidecar with the prepared datasets.

## Acceptance

- `cargo fmt --check && cargo clippy -- -D warnings && cargo test` green; shell test green.
- Full `tauri build` succeeds; DMG size recorded (spec baseline 304.9 MiB with datasets,
  227.3 MiB without).
- `verify-sidecar.sh` passes. No dataset file is committed.
- Installed-app grading check (T-D2.4 second half) is done by the parent session with the owner,
  not in this unit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `runtime/verify_benchmarks.py` (the probe `verify-sidecar.sh`
  runs with the build venv's Python) and `runtime/sign-sidecar.sh` (the Mach-O scan skips
  `benchmark-assets/`).
- **Commits:** `0ab9a7abf` feat(studio): bundle every benchmark dataset and point the runtime at
  it; this ledger in the docs commit that follows.
- **Gates:**
  - `bash src-tauri/tests/before_build_test.sh`: all 14 checks pass (RED first: 8 failed).
  - `cargo test`: 7 passed (3 new `sidecar_args` tests; RED first: did not compile).
  - `cargo clippy -- -D warnings` and `cargo fmt --check` FAIL, and fail identically on
    `origin/main` (checked in a detached worktree): clippy `needless_return` in
    `executable_path` (debug block, unchanged code), and the crate has no `rustfmt.toml` while
    the code is 2-space indented, so `cargo fmt` reformats every file. Not fixed here (out of
    unit); the new code adds no clippy finding.
  - `runtime/verify-sidecar.sh`: `SCREAMINGFACE_BENCHMARKS_LISTED count=8`, then ifeval,
    healthbench-professional, gdpval-text, medxpert, contracteval each `case_loading=completed
    status=succeeded` (score null), `SCREAMINGFACE_SIDECAR_VERIFY_OK`. Against an empty assets
    folder the probe fails (`ifeval: case loading never completed (status failed)`).
  - `tauri build --config '{"bundle":{"createUpdaterArtifacts":false}}'` from
    `apps/screamingface-studio`: succeeds, ad-hoc sidecar signing.
- **DMG size (T-D2.4 build and measure):** 305.1 MiB (319,897,596 bytes) with all six bundles.
  Baseline rebuilt from the same sidecar and frontend without `benchmark-assets/`: 227.4 MiB
  (238,487,737 bytes). Growth +77.7 MiB; spec D10 measured 227.3 → 304.9 MiB, so within ±2 MiB.
  Installed .app 838 MB vs 545 MB.
- **Build time:** first build (empty dataset cache, cold release compile) 234 s; cached
  (`prepare` skips all six) 186 s, then 158–162 s once signing skipped the datasets (the
  `file` scan over ~8,100 dataset files cost ~40 s).
- **Deviations:**
  - `prepare --all` runs from the build venv (`runtime/.venv/bin/screamingface`), not the frozen
    sidecar as the plan wrote: the frozen executable's `prepare` spawns
    `sys.executable -m screamingface_engine.benchmarks.<name>.prepare`, which a PyInstaller
    binary rejects (`invalid choice`). The frozen sidecar still runs the `--list` check, so its
    own fingerprints decide. A follow-up could make frozen `prepare` work, since Studio users
    cannot run it from the app today.
  - `sign-sidecar.sh` skips `benchmark-assets/` (build time only; datasets hold no Mach-O).
  - `verify-sidecar.sh` reads the build cache `runtime/build/benchmark-data/benchmark-assets`
    and fails when it is missing.
  - The second half of T-D2.4 (install the DMG, connect a provider, 3-case IFEval and
    MedXpertQA from the app) is left to the owner session.
