"""A replayed sf.Gate url4 rebuilds the Candidate it was compiled from (E4c, OME-1291).

FEATURE: OME-1291 replay — a Gate's JOIN ``gate_N`` reads only Gate helpers, so the replay links it
to every call in its block; an Operation or member that a Gate ends names ``op_gate_N``; a Gate's
models are listed as panel, bodies, then the selectors it decides with; and only a skip-member
Fanout runs its members' selectors before every member.
STORY: as a benchmark author, I replay any Gate url4 and get back the Candidate I compiled: the same
models in the same order, the same operations, and the same member projections.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
import test_e4c_gate_fixtures as fixtures
from _combine_contract import engine_operators
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.branch import BranchCondition, BranchNode
from screamingface.fusion import FusionNode

_TOPIC = sf.RegexClassifier([("math", r"(?i)\bintegral\b"), ("code", r"(?i)\bpython\b")])
_CLF = sf.LLMClassifier("prov/clf", labels=["safe", "unsafe"])
_TONE = sf.LLMClassifier("prov/tone", labels=["calm", "angry"])


def _replayed(url4: str) -> Candidate:
    return _candidate_from_url4(
        render(
            expr(
                src(text(url4), name="candidate", weight=0.0),
                src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
                intent=text("$rows"),
            )
        )
    )


def _gate(selector, label: str, then, otherwise) -> BranchNode:
    return BranchNode(
        condition=BranchCondition("label", "eq", label, selector), then=then, otherwise=otherwise
    )


def _router() -> sf.Gate:
    code = sf.Gate(when=sf.label(_TOPIC) == "code", then="prov/coder", otherwise="prov/general")
    return sf.Gate(when=sf.label(_TOPIC) == "math", then="prov/math", otherwise=code)


def _recipe(fixture: str) -> object:
    builder: Callable[[], object] = getattr(fixtures, fixture.removesuffix(".url4"))
    return builder()


@pytest.mark.parametrize("fixture", sorted(fixtures.BUILDERS))
def test_every_gate_fixture_replays_to_the_compiled_candidate(fixture: str) -> None:
    compiled = compile_candidate(_recipe(fixture), operators=engine_operators())  # type: ignore[arg-type]

    replayed = _replayed(compiled.url4)

    assert replayed.models == compiled.models
    assert [op.id for op in replayed.operations] == [op.id for op in compiled.operations]
    assert replayed.operations == compiled.operations
    assert replayed.members == compiled.members


def test_a_model_after_a_gate_keeps_the_gate_branch_models_on_replay() -> None:
    # The JOIN names no binding, so the closure from prov/after must cross it to the bodies.
    compiled = compile_candidate(sf.Pipeline([_router(), "prov/after"]))
    assert compiled.models == ("prov/math", "prov/coder", "prov/general", "prov/after")

    assert _replayed(compiled.url4).models == compiled.models


def test_a_fanout_of_label_model_gates_keeps_the_compiled_operation_order() -> None:
    # No member is a skip member: each Gate tree places its own selector, member by member.
    fusion = FusionNode(
        members=[
            _gate(_CLF, "safe", sf.Model("prov/a"), sf.Model("prov/b")),
            _gate(_TONE, "calm", sf.Model("prov/c"), sf.Model("prov/d")),
        ],
        synthesizer=sf.Model("prov/writer"),
    )
    compiled = compile_candidate(fusion)

    replayed = _replayed(compiled.url4)

    assert [op.id for op in replayed.operations] == [op.id for op in compiled.operations]
    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models


def test_a_nested_gate_lists_the_tree_selector_after_every_body() -> None:
    # Only the tree root lists its selectors, so the classifier comes after the otherwise body.
    inner = _gate(_CLF, "safe", sf.Model("prov/a"), sf.Model("prov/b"))
    compiled = compile_candidate(_gate(_TOPIC, "math", inner, sf.Model("prov/c")))
    assert compiled.models == ("prov/a", "prov/b", "prov/c", "prov/clf")

    assert _replayed(compiled.url4).models == compiled.models
