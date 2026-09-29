---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-09-30
finished: 2026-09-30
---

# sdk-drop-kubernetes-runtime — drop the stale `kubernetes` requirement from the runtime

## Intent

The Engine's Kubernetes Job adapter was retired in #822 (`4cdfa920`). Since then no runtime
component imports `kubernetes`. The SDK still lists it in the `runtime` extra, and the local
stack's startup probe (`_RUNTIME_ONLY_MODULES`) still refuses to boot without it.

The frozen Studio sidecar is where this breaks. PyInstaller only bundles what is imported, so
`kubernetes` is not in the bundle. The probe then fails ("Local runtime dependencies are
missing: kubernetes"), and the installed Studio app crashes on launch (OME-1308 / OME-1415).
Removing the stale requirement fixes the crash, and it also drops an unused dependency from every
`pip install screamingface[runtime]`.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/server.py`: remove `"kubernetes"` from
  `_RUNTIME_ONLY_MODULES`, and fix the comment that points at the deleted `adapters.k8s`.
- `packages/screamingface/pyproject.toml`: remove `kubernetes>=31.0.0` from the `runtime` extra.
- `packages/screamingface/uv.lock`: re-lock.
- `packages/screamingface/tests/test_runtime_cli.py`:
  - add a test that neither the probe list nor the `runtime` extra names `kubernetes`;
  - drop `kubernetes` from the set pinned by `test_the_probe_list_pins_the_colab_gap_differentiators`.
    This changes a prior test, which is a Confidence-Gate item; see Deviations.

## Test plan

- RED: the new test fails, because the probe list and the extra both still name `kubernetes`.
- GREEN: after the removal, the full suite and all card gates pass.
- Evidence outside the suite: the frozen Studio sidecar, built from this SDK, boots, and
  `apps/screamingface-studio/runtime/verify-sidecar.sh` passes.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface` passes.
- No `kubernetes` in the runtime extra, the probe list or `packages/screamingface/uv.lock`.

## Outcome

**Actual files:** as planned. That is `packages/screamingface/`:
- `pyproject.toml`
- `uv.lock` (removes `kubernetes`, `durationpy`, `oauthlib`, `requests-oauthlib`)
- `src/screamingface/_runtime/server.py`
- `tests/test_runtime_cli.py`

**Commits:** `fix(screamingface): drop the stale kubernetes requirement from the runtime`.

**Gates** (synced as CI does, `uv sync --extra notebook`, with `--no-config`):
- `ruff check`, `ruff format --check`: pass.
- `pyright`: 0 errors.
- `pytest --cov=screamingface --cov-fail-under=95`: 2004 passed, 26 skipped, 96.09% coverage.
- `check_notebooks.py`, `uv build`, `check_distribution.py`: pass.
- RED first: the new test failed on `'kubernetes' in _RUNTIME_ONLY_MODULES`.
- The append-only check failed on the one approved prior-test change (see Deviations). Every other gate was run individually.

**Deviations:**
- **Prior test changed, approved by the owner on 2026-09-30.**
  `test_the_probe_list_pins_the_colab_gap_differentiators` no longer lists `kubernetes` in its
  pinned set. Its intent (the modules a fresh Colab lacks, OME-1036) is unchanged. The new test
  `test_the_runtime_neither_requires_nor_probes_kubernetes` guards against the dependency coming back.
- The Studio sidecar still has to be re-locked (`apps/screamingface-studio/runtime/uv.lock`) and
  rebuilt once this merges. That happens on OME-1415 / PR #1137, not here.
