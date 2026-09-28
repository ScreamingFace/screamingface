---
id: OME-1263
linear_url: https://linear.app/openmined/issue/OME-1263/restructure-url4-by-layer-split-the-hotspot-modules-close-the
status: In Progress
type: task
priority: Medium
labels: [url4-sdk, agentic, autonomous]
created: 2026-09-22
closed:
related: [OME-537, OME-539, OME-546]
---

# Restructure url4 by layer: split the hotspot modules, close the vocabularies, enforce the boundaries in CI

Structural pass over `packages/url4`. Splits the four modules that each carried several
reasons to change (`dag/nodes.py` 1062, `cli/_serve.py` 661, `dag/executor.py` 524,
`peer/server.py` 501) behind facades that re-export every public name, closes the open
`str` vocabularies (`ErrorCode`, iteration `on_error`, log-drop reason), and removes the
duplicated ASGI plumbing across the two entrypoints.

The durable part is the enforcement: `ARCHITECTURE.md` states the three layers
(language → engine → node) and `tests/unit/test_layering.py` checks the import direction
over the source AST; `scripts/check_module_size.py` caps the 17 largest modules;
`tests/formal/` machine-checks the executor-memo and spawn-cache atomic check-then-act
with paired fixed/buggy models.

Delivers two open sub-issues of OME-537 — **OME-539** (wire codec out of `core/`) and
**OME-546** (shared ASGI helpers + the `aclose` asymmetry) — which should be closed
against this branch. The rest of the OME-537 family stays open.

Three behaviour changes, all recorded in the ledger: the `check=False` fast path on the
SDK front doors, the `RenderError` blame restored on top of it, and the sequence-invariant
asserts inlined so `-O` strips them.

Ledger: `docs/work/2026-09-22-OME-1263-url4-layer-restructure.md`
