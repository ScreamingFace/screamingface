"""The shared world package (prd/01 F1).

# WHY this package exists. Both halves of the engine need the same world: the run mode builds it
# per Job and runs an expression against it; the control plane (unit 3) will serve mounts from a
# long-lived node. Before F1 the world-building code lived in `runner/`, so the control plane could
# not reach it without importing the run mode — and `check_layering.py` forbade exactly that.
#
# `world/` is therefore its own category: importable by BOTH halves, importing NEITHER. It depends
# only on `packages/url4`, the standard library, and engine shared leaves (`job_env`,
# `request_scope`, `observations`, ...). It must never import `runner`, the control plane, or the
# worker; `check_layering.py` proves it, and `tests/unit/test_layering_world.py` pins the rule
# with fixtures.
#
# F2 (the request scope) is what makes one world safe to share: the connector reads caller state
# from the `request_scope` ContextVar per call, so nothing here holds a caller's identity.
"""

__all__: list[str] = []
