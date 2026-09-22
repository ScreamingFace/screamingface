"""The three-layer import direction holds — language ← engine ← node.

STORY: as a contributor I can tell where a module belongs from its layer, and
the boundary does not erode silently. The rule is:

    url4.core       LANGUAGE  text <-> AST.   Imports nothing above it.
    url4.wire       shared    the ?q= codec.   Imports core only.
    url4.dag        ENGINE    AST -> execute.  May import core, wire, io, observe.
    url4.io         PORT      + adapters.      Must not import the engine.
    url4.observe    leaf      Must not import the engine or a transport.
    url4.peer       NODE      server + client. May import everything below it.
    url4.cli        NODE      composition root. May import everything below it.
    url4.streaming  separate  the wire contract. Imports no engine module.

This checks the SOURCE with an AST walk, so function-local and TYPE_CHECKING
imports are seen too — exactly where a boundary violation likes to hide.
`tests/unit/test_import_isolation.py` proves the runtime half (a fresh
interpreter pulls in no framework); this proves the compile-time half.

`url4/__init__.py` (the public composition root) and `url4/_log_attributes.py`
(a stdlib-only leaf) are outside this matrix and skipped.
"""

from __future__ import annotations

import ast
from pathlib import Path

import url4

_SRC = Path(url4.__file__).parent

# The layer a dotted module belongs to, by prefix. A module outside these
# prefixes (`url4`, `url4._log_attributes`) maps to None and is skipped.
_LAYER_FOR_PREFIX = {
    "url4.core": "core",
    "url4.wire": "wire",
    "url4.dag": "dag",
    "url4.io": "io",
    "url4.observe": "observe",
    "url4.peer": "peer",
    "url4.cli": "cli",
    "url4.streaming": "streaming",
}

# importer layer -> layers it may NOT import. Everything omitted is allowed.
_FORBIDDEN: dict[str, set[str]] = {
    "core": {"wire", "dag", "io", "observe", "peer", "cli", "streaming"},
    "wire": {"dag", "io", "observe", "peer", "cli", "streaming"},
    "dag": {"peer", "cli", "streaming"},
    "io": {"dag", "peer", "cli", "streaming"},
    "observe": {"dag", "io", "peer", "cli", "streaming"},
    "peer": {"cli", "streaming"},
    "cli": {"streaming"},
    "streaming": {"core", "wire", "dag", "io", "observe", "peer", "cli"},
}


def _layer_of(module: str) -> str | None:
    """The layer a dotted module belongs to, or None when it is not in the matrix."""
    for prefix, layer in _LAYER_FOR_PREFIX.items():
        if module == prefix or module.startswith(f"{prefix}."):
            return layer
    return None


def _importer_layer(path: Path) -> str | None:
    """The layer a source file belongs to, or None when it is outside the matrix."""
    rel = path.relative_to(_SRC)
    if rel.name == "observe.py" and len(rel.parts) == 1:
        return "observe"
    if len(rel.parts) >= 2 and rel.parts[0] in _FORBIDDEN:
        return rel.parts[0]
    return None


def _is_url4(name: str) -> bool:
    return name == "url4" or name.startswith("url4.")


def _from_modules(node: ast.ImportFrom, package: list[str]) -> set[str]:
    """The absolute url4 module names a ``from … import …`` resolves to."""
    if node.level == 0:
        return {node.module} if node.module and _is_url4(node.module) else set()
    base = package[: len(package) - (node.level - 1)]
    if node.module:
        return {".".join([*base, node.module])}
    return {".".join([*base, alias.name]) for alias in node.names}  # `from . import x`


def _imported_modules(path: Path) -> set[str]:
    """Every ``url4.*`` module ``path`` imports, absolute names, relative resolved.

    Sees function-local and TYPE_CHECKING imports because it walks the whole
    AST. A bare ``from url4 import X`` resolves to ``url4`` and is skipped: the
    binding's layer cannot be known statically, and the root package is the
    composition root by design.
    """
    found: set[str] = set()
    # The dotted package this file lives in: core/grammar.py -> ["url4", "core"].
    package = ["url4", *path.relative_to(_SRC).parts[:-1]]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if _is_url4(alias.name))
        elif isinstance(node, ast.ImportFrom):
            found.update(_from_modules(node, package))
    return found


def _offenders(source_layer: str) -> list[str]:
    """Every import in ``source_layer`` that crosses into a forbidden layer."""
    forbidden = _FORBIDDEN[source_layer]
    result: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if _importer_layer(path) != source_layer:
            continue
        for module in sorted(_imported_modules(path)):
            if _layer_of(module) in forbidden:
                result.append(f"{path.relative_to(_SRC)} imports {module}")
    return result


def test_the_walk_actually_sees_every_layer() -> None:
    # Without this, a typo in the path logic would make every assertion below
    # pass vacuously forever (mirrors the detector sanity check in
    # test_import_isolation.py).
    seen = {_importer_layer(p) for p in _SRC.rglob("*.py")} - {None}
    assert seen == {"core", "wire", "dag", "io", "observe", "peer", "cli", "streaming"}


def test_language_layer_imports_nothing_above_it() -> None:
    assert _offenders("core") == []


def test_wire_layer_imports_only_language() -> None:
    assert _offenders("wire") == []


def test_engine_layer_does_not_reach_the_node_layer() -> None:
    assert _offenders("dag") == []


def test_io_port_does_not_depend_on_the_engine() -> None:
    assert _offenders("io") == []


def test_observe_is_a_leaf() -> None:
    assert _offenders("observe") == []


def test_peer_does_not_import_the_cli() -> None:
    assert _offenders("peer") == []


def test_cli_does_not_import_the_wire_contract() -> None:
    assert _offenders("cli") == []


def test_streaming_imports_no_engine_module() -> None:
    assert _offenders("streaming") == []
