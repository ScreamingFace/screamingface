"""Inert text: quoted URL4 text whose ``$`` is never interpolated (spec B §6.2, §6.3).

Split from ``builders.py`` by reason to change: literal escaping changes with the
interpolation rules, not with the expression builders.
"""

from __future__ import annotations

from url4.core.nodes import Text


def literal(content: str) -> Text:
    """Text that resolves to ``content`` exactly: no ``$`` in it is ever interpolated.

    Each ``$`` becomes the grammar's literal dollar ``$$`` (§6.2). WHY: in an RDS scope quoted
    text is interpolated strictly (§6.3), so inert text that holds ``$name`` — e.g. a Recipe
    carried as data — would fail as an unbound reference. :func:`literal_value` inverts it.
    """
    return Text(content.replace("$", "$$"))


def literal_value(node: Text) -> str:
    """The content a :func:`literal` node resolves to (``$$`` read back as ``$``)."""
    return node.value.replace("$$", "$")


__all__ = ["literal", "literal_value"]
