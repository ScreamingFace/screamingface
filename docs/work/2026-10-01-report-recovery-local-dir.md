---
ticket: OME-1448
stack: screamingface
status: in_progress
started: 2026-10-01
finished:
---

# report-recovery-local-dir — Keep local spilled results across a reboot (OME-1448, PR B)

## Intent

`screamingface up` leaves the local Engine's spilled results in
`$TMPDIR/screamingface-engine/artifacts`. Ubuntu wipes that folder on reboot, so a recovery
record can point at bytes that no longer exist (OME-1448 failure F3). This unit moves the default
folder to `<data_dir>/artifacts`, with mode 0700. It keeps the writer (run env) and the reader
(`EngineSettings`) on the same value (the OME-929 lesson), and a user's `URL4_CLOUD_ARTIFACTS_DIR`
still wins on both sides. Plan: `docs/plan/2026-10-01-OME-1448-report-recovery.md` §PR B. Spec:
`docs/spec/2026-10-01-OME-1448-report-recovery/prd/local-durable-artifacts.md` (the spec lands
with PR A).

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/config.py`: `RuntimeConfig.artifacts_dir`.
- `packages/screamingface/src/screamingface/_runtime/server.py`: `_build_apps` sets one artifacts folder on both sides.
- `packages/screamingface/src/screamingface/_runtime/cli.py` (Should): `status` shows the folder and its size.
- New tests: `tests/test_runtime_artifacts_dir.py`.
- `packages/screamingface/CHANGELOG.md`.

## Test plan

Spec rows LA-0 (CHAR: an env override reaches both sides; passes today), LA-1, LA-2, LA-4 …
LA-8. RED first: LA-1 (the writer and the reader use the same folder, and it is
`<data_dir>/artifacts`).

## Acceptance

- Every existing runtime test is unchanged and green. The new tests are green. The
  `run_gates.py screamingface` gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/src/screamingface/_runtime/config.py` (`artifacts_dir`,
  `artifacts_override`, `effective_artifacts_dir`, `ARTIFACTS_DIR_ENV`), `.../_runtime/server.py`
  (`_build_apps`: one folder on both sides; the default folder is created and re-chmodded 0700),
  `.../_runtime/cli.py` (the state record carries the effective `artifacts_dir`; `status` reads it
  and shows the size, `size unknown` when the folder cannot be listed, and survives a file swept
  during the count), `packages/screamingface/tests/test_runtime_artifacts_dir.py` (new, 19 tests),
  `packages/screamingface/CHANGELOG.md`.
- **Commits:**
- **Gates:** see the commit; `uv run .claude/scripts/run_gates.py screamingface` -> ALL GATES GREEN.
- **Deviations:**
  1. The SDK test env has no runtime extra, so the tests stub `aigateway.config`, `aigateway.main`,
     `screamingface_engine.config` and `screamingface_engine.local`. The Engine settings stub only
     records its kwargs. That is honest, because `_build_apps` now always passes `artifacts_dir`
     explicitly. A test pins `ARTIFACTS_DIR_ENV` to `job_env.ARTIFACTS_DIR`.
  2. Spec rows LA-4 (restart) and LA-8 (48 h sweep) were dropped. The design review found that they
     only exercised the Engine's `FilesystemArtifactStore`, so they could not fail because of this
     change. LA-1 gives the SDK-side guarantee. The spec test table is updated in PR A.
  3. Review fixes added after the first pass: `status` reports the folder the server recorded in
     its state record (OME-1169 pattern), not this shell's default; the default folder is
     re-chmodded 0700 when it already exists; "override set" decides the mkdir, not a string
     compare; an unlistable folder shows `size unknown`; the CHANGELOG names the upgrade effects.
     These fixes were coded before their tests, so RED was proven by mutation: each test fails
     with its fix reverted.
  4. The state-record key itself (`"artifacts_dir"` in `_serve_logged`) has no direct test. The
     rule it calls (`effective_artifacts_dir`) is unit-tested, and `_runtime` is outside the
     coverage scope.
  5. The CHANGELOG entry is under Unreleased "Features", because the file has no "Changed" heading.
