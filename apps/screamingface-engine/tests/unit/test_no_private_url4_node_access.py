"""No Engine module reads a private attribute of a url4 node.

STORY: as an Engine maintainer, I read a url4 node's state through its public members
(``Url4Node.eval_path``, ``Url4Node.holdings_collections()``, ``url4.peer.describe_routes``) and
never through the ``_``-prefixed fields it keeps for itself.

WHY: the private field names come from a LIVE ``Url4Node``, not a hand-kept list, so the set
cannot go stale when url4 renames or adds a field. A hand-kept list would miss the next one.

INVARIANT: an attribute access ``x.<private>`` is an offender unless ``x`` is ``self`` or ``cls``
(an Engine class reading its own ``self._data`` is not a url4 read). A
``getattr``/``hasattr``/``setattr`` call with a private name string is an offender too, so the
access cannot hide behind a string.
"""

from __future__ import annotations

import ast
from pathlib import Path

from url4.peer.server import Url4Node

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "screamingface_engine"
_OWN_NAMES = frozenset({"self", "cls"})
_STRING_ACCESSORS = frozenset({"getattr", "hasattr", "setattr"})


def _private_url4_node_attributes() -> frozenset[str]:
    node = Url4Node("probe")
    return frozenset(
        name for name in vars(node) if name.startswith("_") and not name.startswith("__")
    )


def _offending_lines(py_file: Path, private: frozenset[str]) -> list[int]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in private:
            if not (isinstance(node.value, ast.Name) and node.value.id in _OWN_NAMES):
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _STRING_ACCESSORS
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in private
        ):
            lines.append(node.lineno)
    return lines


def test_no_engine_module_reads_a_private_url4_node_attribute() -> None:
    private = _private_url4_node_attributes()
    assert private, "a live Url4Node must expose private fields for this guard to mean anything"
    offenders = [
        f"{py_file.relative_to(_SRC_ROOT.parent.parent)}:{line}"
        for py_file in sorted(_SRC_ROOT.rglob("*.py"))
        for line in _offending_lines(py_file, private)
    ]
    assert offenders == [], f"private url4 node attribute read: {offenders}"
