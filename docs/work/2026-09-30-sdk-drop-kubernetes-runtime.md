---
ticket: OME-1417
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
- `packages/screamingface/tests/test_runtime_cli.py`: drop `kubernetes` from the set pinned by
  `test_the_probe_list_pins_the_colab_gap_differentiators`. This changes a prior test, which is a
  Confidence-Gate item; see Deviations.

## Test plan

- RED: the updated pinned-set test fails, because the probe list still names `kubernetes`.
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
- RED first: a guard test failed on `'kubernetes' in _RUNTIME_ONLY_MODULES`. It was later removed; see Deviations.
- The append-only check failed on the one approved prior-test change (see Deviations). Every other gate was run individually.

**Deviations:**
- **Prior test changed, approved by the owner on 2026-09-30.**
  `test_the_probe_list_pins_the_colab_gap_differentiators` no longer lists `kubernetes` in its
  pinned set. Its intent (the modules a fresh Colab lacks, OME-1036) is unchanged.
- **The guard test and the "WHY no kubernetes" comment were removed in review, at the owner's
  call.** No repo rule requires either. The updated pinned-set test is enough to drive the
  change, and a comment about a dependency that is gone only means something during review. What
  is actually worth testing is whether the frozen sidecar launches, which is out of scope here.
- The Studio sidecar still has to be re-locked (`apps/screamingface-studio/runtime/uv.lock`) and
  rebuilt once this merges. That happens on OME-1415 / PR #1137, not here.
