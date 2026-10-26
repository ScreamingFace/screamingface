"""A sf.Keywords pattern holding ``$`` reaches the Engine byte-identical (E4c, OME-1291).

url4 interpolates ``$name`` / ``$N`` inside an intent at resolve time (spec §8.2.5), so a raw
``$`` in the selector spec text is read as a reference: ``\\$input`` would be replaced by the
Case input and ``\\$gate_1`` would add a dependency edge on a binding the author never named.
"""

from __future__ import annotations

import json

from url4 import Expression, RelExpr, Text, build, walk
from url4.core.context import Context
from url4.dag.semantics.ensemble import find_references, interpolate

import screamingface as sf
from screamingface._evaluation.branch import DECIDE_ROUTE, KEYWORDS_ROUTE
from screamingface._evaluation.candidate import compile_candidate
from screamingface.branch import BranchCondition, BranchNode

_PATTERNS = (r"\$input", r"cost in \$gate_1", r"\$\$1 \$1", r"total\$")


def _intents(route: str) -> list[str]:
    selector = sf.Keywords([(f"l{index}", pattern) for index, pattern in enumerate(_PATTERNS)])
    gate = BranchNode(
        condition=BranchCondition("label", "eq", "l0", selector),
        then=sf.Model("prov/a"),
        otherwise=sf.Model("prov/b"),
    )
    root = build(compile_candidate(gate).url4)
    assert isinstance(root, Expression)
    found = [
        node.intent.value
        for node in walk(root)
        if isinstance(node, RelExpr) and node.path == route and isinstance(node.intent, Text)
    ]
    assert found, f"no {route} call in the compiled expression"
    return found


def _resolved(intent: str) -> object:
    # The scope a real run gives the call: the Case input and every gate binding are bound.
    scope = Context.root().child(input="CASE INPUT", gate_1="GATE", **{"1": "ONE"})
    return json.loads(interpolate(intent, scope))


def test_keywords_patterns_with_dollar_reach_the_engine_byte_identical() -> None:
    for intent in _intents(KEYWORDS_ROUTE):
        assert find_references(intent) == set()
        specs = _resolved(intent)
        assert isinstance(specs, dict)
        (spec,) = specs.values()
        assert tuple(rule["pattern"] for rule in spec["rules"]) == _PATTERNS


def test_decide_spec_rules_with_dollar_reach_the_engine_byte_identical() -> None:
    for intent in _intents(DECIDE_ROUTE):
        spec = _resolved(intent)
        assert isinstance(spec, dict)
        (declared,) = spec["selectors"].values()
        assert tuple(rule["pattern"] for rule in declared["rules"]) == _PATTERNS
