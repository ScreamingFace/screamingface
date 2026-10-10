"""Ratchet: one url4 package reaching into another package's private names may only go down.

STORY: as a contributor I can tell a module's real API from its private helpers, and the
number of places that cross a package boundary through a private name does not grow
silently (audit HY-4).

A crossing is an import, in a module of one layer (``core``, ``wire``, ``dag``, ``io``,
``observe``, ``peer``, ``cli``, ``streaming``), of a module of ANOTHER layer that is private
(a path segment starts with ``_``, such as ``url4.peer._asgi``) or of a private name from
it (``from url4.core.grammar import _IDENTITY_NAME_RE``). Imports inside one layer are
free: a package owns its private helpers. ``url4/__init__.py`` and ``url4._log_attributes``
(a stdlib-only leaf outside the layer matrix) are skipped, as in ``test_layering.py``.

When a crossing goes away for good, lower :data:`BASELINE`. Never raise it to make CI
pass: make the name public in its home module instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import url4

_SRC = Path(url4.__file__).parent

# Count measured when this ratchet was added (2026-10-10).
BASELINE = 21

_LAYERS = ("core", "wire", "dag", "io", "observe", "peer", "cli", "streaming")


def _layer_of(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "url4" or len(parts) < 2:
        return None
    return parts[1] if parts[1] in _LAYERS else None


def _importer_layer(path: Path) -> str | None:
    rel = path.relative_to(_SRC)
    if rel.parts == ("observe.py",):
        return "observe"
    return rel.parts[0] if len(rel.parts) >= 2 and rel.parts[0] in _LAYERS else None


def _is_private(segment: str) -> bool:
    return segment.startswith("_") and not segment.startswith("__")


def _absolute(node: ast.ImportFrom, rel: str) -> str | None:
    if node.level == 0:
        return node.module
    package = ["url4", *rel.split("/")[:-1]]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _crossings(path: Path, layer: str) -> list[str]:
    """Every private crossing in ``path``, as ``file: module[.name]``."""
    return _crossings_in(path.read_text(encoding="utf-8"), path.relative_to(_SRC).as_posix(), layer)


def _crossings_in(source: str, rel: str, layer: str) -> list[str]:
    """Every private crossing in ``source``, the text of the module at ``rel`` in ``layer``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.Import):
            targets = [(alias.name, None) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node, rel)
            targets = [(module, alias.name) for alias in node.names] if module else []
        else:
            continue
        for module, name in targets:
            other = _layer_of(module)
            if other is None or other == layer:
                continue
            private_module = any(_is_private(part) for part in module.split(".")[2:])
            if private_module or (name is not None and _is_private(name)):
                found.append(f"{rel}: {module}" + (f".{name}" if name else ""))
    return found


def _all_crossings() -> list[str]:
    found: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        layer = _importer_layer(path)
        if layer is not None:
            found.extend(_crossings(path, layer))
    return found


def test_the_walk_sees_every_kind_of_crossing() -> None:
    # Without this, a bug in the walk would make the ratchet pass vacuously forever. A
    # synthetic module keeps the check stable when a real crossing is promoted away.
    source = (
        "from url4.core.grammar import _NAME, public\n"
        "from ..core import _helper\n"
        "import url4.peer._asgi\n"
        "from url4.dag import _same_layer\n"
        "from ._sibling import thing\n"
    )
    assert _crossings_in(source, "dag/x.py", "dag") == [
        "dag/x.py: url4.core.grammar._NAME",
        "dag/x.py: url4.core._helper",
        "dag/x.py: url4.peer._asgi",
    ]


def test_cross_package_private_imports_do_not_grow() -> None:
    crossings = _all_crossings()
    assert len(crossings) <= BASELINE, "\n".join(
        [f"{len(crossings)} private crossings > baseline {BASELINE}:", *crossings]
    )
