"""Unit 7c of the swap: the gate references on ``sf.signal`` and ``>>`` on every recipe (D7-3).

FEATURE: ``sf.signal(x).chosen()`` and ``sf.signal(x).mean()`` are gate references on the one
``Signal`` class, so ``sf.signal`` and the new surface's ``signal`` are the same function.
FEATURE: a recipe on either side of ``>>`` (``sf.Model(...) >> x``, ``"route" >> sf.Model(...)``)
builds a chain, as a step does.
"""

from __future__ import annotations

import pytest
from _nodes import VoteNode, fusion_node

import screamingface as sf
from screamingface import _surface as sx
from screamingface._signals import Signal
from screamingface._surface.chain import Pipeline as Chain
from screamingface._surface.refs import GateRef

_ROUTES = ["prov/a", "prov/b"]


def test_sf_signal_gives_the_gate_references() -> None:
    risk = sf.signal("risk")

    assert type(risk) is Signal
    assert risk.chosen() == GateRef("chosen:risk")
    assert risk.mean() == GateRef("mean:risk")
    assert sx.signal is sf.signal


@pytest.mark.parametrize("method", ["chosen", "mean"])
def test_si1_an_e4a_key_is_not_a_gate_input(method: str) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^sf\.signal\('cost_usd'\)\.{method}\(\) reads a declared signal; an E4a key such "
        r"as cost_usd is not a gate input$",
    ):
        getattr(sf.signal("cost_usd"), method)()


def test_a_recipe_on_the_left_of_rshift_builds_a_chain() -> None:
    a, b = sf.Model("prov/a"), sf.Model("prov/b")
    # WHY the node: a recipe that is not a chain (the chain on the left is the next test's row)
    fusion = fusion_node(_ROUTES, VoteNode())
    today = sf.Pipeline([a, b])

    assert a >> b == Chain([a, b])
    assert a >> "prov/b" == Chain([a, "prov/b"])
    assert fusion >> b == Chain([fusion, b])
    assert today >> "prov/c" == Chain([today, "prov/c"])


def test_a_route_on_the_left_of_a_recipe_builds_a_chain() -> None:
    b = sf.Model("prov/b")

    assert "prov/a" >> b == Chain(["prov/a", b])


def test_a_chain_and_a_recipe_flatten_into_one_chain() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Vote()
    b = sf.Model("prov/b")

    assert (chain >> b).steps == (*chain.steps, b)
    assert (b >> chain).steps == (b, *chain.steps)
