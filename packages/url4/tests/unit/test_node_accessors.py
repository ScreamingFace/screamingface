"""Public read accessors on ``Url4Node``: ``eval_path`` and ``holdings_collections()``.

STORY: as a host that mounts a node, I read the node's eval path and its named holdings shelves
through public members, not through private ``_eval_path`` / ``_self_holdings`` fields.

INVARIANT: both accessors are read-only views. ``eval_path`` is a property with no setter, and
``holdings_collections()`` returns a ``frozenset`` snapshot, so a caller cannot change the node
by holding the answer.
"""

from __future__ import annotations

import pytest

from url4.peer.server import Url4Node


def test_eval_path_defaults_to_url4_eval_path() -> None:
    assert Url4Node("t").eval_path == "/v1"


def test_eval_path_reports_the_constructor_value() -> None:
    assert Url4Node("t", eval_path="/eval").eval_path == "/eval"


def test_eval_path_is_read_only() -> None:
    node = Url4Node("t")
    with pytest.raises(AttributeError):
        setattr(node, "eval_path", "/other")


def test_holdings_collections_is_empty_for_a_fresh_node() -> None:
    assert Url4Node("t").holdings_collections() == frozenset()


def test_holdings_collections_names_the_default_shelf_as_none_and_each_named_shelf() -> None:
    node = Url4Node("t")

    @node.holdings
    def _default() -> str:
        return "default"

    @node.holdings("science")
    def _science() -> str:
        return "science"

    assert node.holdings_collections() == frozenset({None, "science"})


def test_holdings_collections_is_a_frozenset() -> None:
    node = Url4Node("t")

    @node.holdings("science")
    def _science() -> str:
        return "science"

    collections = node.holdings_collections()
    assert isinstance(collections, frozenset)
    with pytest.raises(AttributeError):
        getattr(collections, "add")("other")
