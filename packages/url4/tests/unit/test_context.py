"""The immutable parent-pointer scope chain."""

from __future__ import annotations

import pytest

from url4.core.context import Context
from url4.core.errors import ScopeError


def test_lookup_in_own_frame() -> None:
    assert Context.root().child(a="1").lookup("a") == "1"


def test_lookup_walks_parent_chain() -> None:
    root = Context.root().child(a="1")
    nested = root.child(b="2")
    assert nested.lookup("a") == "1"
    assert nested.lookup("b") == "2"


def test_child_does_not_mutate_parent() -> None:
    parent = Context.root().child(a="1")
    parent.child(a="2")
    assert parent.lookup("a") == "1"


def test_nearest_binding_shadows() -> None:
    outer = Context.root().child(a="outer")
    inner = outer.child(a="inner")
    assert inner.lookup("a") == "inner"
    assert outer.lookup("a") == "outer"


def test_unbound_raises_scope_error() -> None:
    with pytest.raises(ScopeError):
        Context.root().lookup("missing")


def test_get_in_own_frame() -> None:
    assert Context.root().child(a="1").get("a") == "1"


def test_get_walks_parent_chain() -> None:
    nested = Context.root().child(a="1").child(b="2")
    assert nested.get("a") == "1"
    assert nested.get("b") == "2"


def test_get_nearest_binding_shadows() -> None:
    outer = Context.root().child(a="outer")
    inner = outer.child(a="inner")
    assert inner.get("a") == "inner"
    assert outer.get("a") == "outer"


def test_get_absent_returns_default() -> None:
    assert Context.root().get("missing") is None
    assert Context.root().child(a="1").get("missing") is None
    assert Context.root().get("missing", "fallback") == "fallback"
