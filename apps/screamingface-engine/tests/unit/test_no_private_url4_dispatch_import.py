"""SC1 / MNT-5 (contracts.md C11): the engine speaks only url4's PUBLIC `url4.peer` API.

`url4.peer._dispatch` and `url4.peer._http` are package-private — the direct-call guarantee
(spec D1) lives in the public `url4.peer.direct` module precisely so a host that queues mount
calls and runs them elsewhere never re-derives it from private registries on the other side of
a queue. An AST scan (not a runtime import check) so an offender fails even if nothing happens
to exercise the import at collection time.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

_FORBIDDEN_MODULES = frozenset({"url4.peer._dispatch", "url4.peer._http"})


def _imports_private_url4_peer(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name in _FORBIDDEN_MODULES for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_MODULES:
            return True
    return False


def test_no_module_imports_a_private_url4_peer_dispatch_module() -> None:
    """Every `screamingface_engine` module reaches url4's direct-call/dispatch behavior
    through the public `url4.peer` API alone (`dispatch_direct`, `describe_routes`,
    `http_status`) — never the package-private `_dispatch`/`_http` it is built from."""
    offenders = [
        py_file
        for py_file in (_SRC_ROOT / "screamingface_engine").rglob("*.py")
        if _imports_private_url4_peer(py_file)
    ]
    assert offenders == []


_PRIVATE_PEER_PREFIX = "url4.peer._"


def _is_private_peer_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.startswith(_PRIVATE_PEER_PREFIX) for alias in node.names)
    if not isinstance(node, ast.ImportFrom) or node.module is None:
        return False
    # WHY: `from url4.peer import _dispatch` loads the private submodule through the package,
    # and `from url4.peer.server import _dispatch` reaches it through a name a module binds;
    # both import a private `url4.peer` name without naming the module.
    in_peer = node.module == "url4.peer" or node.module.startswith("url4.peer.")
    return node.module.startswith(_PRIVATE_PEER_PREFIX) or (
        in_peer and any(alias.name.startswith("_") for alias in node.names)
    )


def _imports_any_private_url4_peer(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    return any(_is_private_peer_import(node) for node in ast.walk(tree))


def test_no_module_imports_any_private_url4_peer_module() -> None:
    """The same guarantee for EVERY package-private `url4.peer._*` module, not a fixed list.

    WHY: url4 2.0 split `_dispatch` into `_request` and `_code_pointer`, and a named list goes
    stale on every such split. A prefix covers the next private module too (O8, 2026-10-09).
    """
    offenders = [
        py_file
        for py_file in (_SRC_ROOT / "screamingface_engine").rglob("*.py")
        if _imports_any_private_url4_peer(py_file)
    ]
    assert offenders == []
