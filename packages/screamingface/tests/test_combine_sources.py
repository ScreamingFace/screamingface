"""The combine context's `sources` for accounting-signal reducers (OME-1289, SG#5/6/9/20).

FEATURE: a reducer that reads cost_usd, latency_ms, tokens_in or tokens_out adds `sources`: the
model calls each member made, by the (path, params) fingerprint the Engine records.
INVARIANT: a member with a call that is claimed twice anywhere in the expression gets `{}` (F3).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

import pytest
from _combine_contract import engine_operators
from _reducer_fixtures import FixtureVote, fixture_operators
from url4 import build, render, struct

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)
_COST = sf.signal("cost_usd")


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators(), check_surface=_SURFACE).url4


def context_of(url4: str, binding: str) -> str:
    """The context text of one call of the candidate (it equals `render(struct(...))`, F6)."""

    for source in build(url4).sources:  # type: ignore[union-attr]
        if source.name == binding:
            return source.value.context  # type: ignore[union-attr]
    raise AssertionError(f"no call {binding!r} in the candidate")


def _call(path: str, params: str = "") -> dict[str, str]:
    return {"path": path, "params": params}


def _context(outputs: dict[str, str], sources: dict[str, Any] | None = None) -> str:
    value: dict[str, Any] = {"input": "$input", "outputs": outputs}
    if sources is not None:
        value["sources"] = sources
    return render(struct(value))


def _mixed(synthesizer: Reducer) -> sf.Fusion:
    members = [sf.Model("p/a", params={"temperature": 0.5}), "p/b", sf.Pipeline(["p/c", "p/d"])]
    return sf.Fusion(members, synthesizer=synthesizer)


_MIXED_OUTPUTS = {"member_1": "$model_1", "member_2": "$model_2", "member_3": "$model_4"}


@pytest.mark.parametrize("key", ["cost_usd", "latency_ms", "tokens_in", "tokens_out"])
def test_compile_emits_sources_only_when_accounting_signal_is_read(key: str) -> None:
    sources = {
        "member_1": {"model_1": _call("/p/a", "temperature=0.5")},
        "member_2": {"model_2": _call("/p/b")},
        "member_3": {"model_3": _call("/p/c"), "model_4": _call("/p/d")},
    }
    url4 = _url4(_mixed(sf.Vote(weights=sf.signal(key))))

    assert context_of(url4, "synthesis_1") == _context(_MIXED_OUTPUTS, sources)


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Vote(weights=sf.signal("field:confidence")),
        sf.Vote(weights=[1, 2, 3]),
        sf.Vote(),
        sf.Median(),
    ],
    ids=repr,
)
def test_no_sources_when_no_accounting_signal_is_read(synthesizer: Reducer) -> None:
    url4 = _url4(_mixed(synthesizer))

    assert context_of(url4, "synthesis_1") == _context(_MIXED_OUTPUTS)


def _duplicates() -> sf.Recipe:
    return sf.Fusion(["p/a", "p/a", "p/b"], synthesizer=sf.Vote(weights=_COST))


def _nested() -> sf.Recipe:
    inner_a = sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote())
    inner_b = sf.Fusion(["p/a", "p/c"], synthesizer=sf.Vote())
    return sf.Fusion([inner_a, inner_b, "p/d"], synthesizer=sf.Vote(weights=_COST))


def _reuse_after() -> sf.Recipe:
    fusion = sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote(weights=_COST))
    return sf.Pipeline([fusion, "p/a"])


def _prompts() -> sf.Recipe:
    members = [sf.Model("p/a", prompt="x"), sf.Model("p/a", prompt="y")]
    return sf.Fusion(members, synthesizer=sf.Vote(weights=_COST))


def _samples() -> sf.Recipe:
    return sf.Fusion(sf.samples("p/a", 3), synthesizer=sf.Vote(weights=_COST))


def _model_synthesizer_member() -> sf.Recipe:
    inner = sf.Fusion(["p/a", "p/b"], synthesizer="p/s")
    return sf.Fusion([inner, "p/c"], synthesizer=sf.Vote(weights=_COST))


def _reducer_member() -> sf.Recipe:
    inner = sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote())
    return sf.Fusion([inner, "p/c"], synthesizer=sf.Vote(weights=_COST))


_AB = {"member_1": "$model_1", "member_2": "$model_2"}
# id -> (recipe, the outer reducer's binding, outputs, expected sources, DuplicateMembersWarnings)
_CLAIMS: list[tuple[str, Callable[[], sf.Recipe], str, dict[str, str], dict[str, Any], int]] = [
    (
        "duplicate members",
        _duplicates,
        "synthesis_1",
        {**_AB, "member_3": "$model_3"},
        {"member_1": {}, "member_2": {}, "member_3": {"model_3": _call("/p/b")}},
        1,
    ),
    (
        "nested fusions reusing a model",
        _nested,
        "synthesis_3",
        {"member_1": "$synthesis_1", "member_2": "$synthesis_2", "member_3": "$model_5"},
        {"member_1": {}, "member_2": {}, "member_3": {"model_5": _call("/p/d")}},
        0,
    ),
    (
        "reuse after the fusion",
        _reuse_after,
        "synthesis_1",
        _AB,
        {"member_1": {}, "member_2": {"model_2": _call("/p/b")}},
        0,
    ),
    (
        "same request, different prompts",
        _prompts,
        "synthesis_1",
        _AB,
        {"member_1": {}, "member_2": {}},
        0,
    ),
    (
        "samples",
        _samples,
        "synthesis_1",
        {**_AB, "member_3": "$model_3"},
        {f"member_{k}": {f"model_{k}": _call("/p/a", f"seed={k - 1}")} for k in (1, 2, 3)},
        0,
    ),
    (
        "model synthesizer member",
        _model_synthesizer_member,
        "synthesis_2",
        {"member_1": "$synthesis_1", "member_2": "$model_3"},
        {
            "member_1": {
                "model_1": _call("/p/a"),
                "model_2": _call("/p/b"),
                "synthesis_1": _call("/p/s"),
            },
            "member_2": {"model_3": _call("/p/c")},
        },
        0,
    ),
    (
        "reducer member",
        _reducer_member,
        "synthesis_2",
        {"member_1": "$synthesis_1", "member_2": "$model_3"},
        {
            "member_1": {"model_1": _call("/p/a"), "model_2": _call("/p/b")},
            "member_2": {"model_3": _call("/p/c")},
        },
        0,
    ),
]


@pytest.mark.parametrize(
    ("recipe", "binding", "outputs", "sources", "warned"),
    [row[1:] for row in _CLAIMS],
    ids=[row[0] for row in _CLAIMS],
)
def test_fingerprint_claimed_twice_in_expression_is_left_out_of_sources(
    recipe: Callable[[], sf.Recipe],
    binding: str,
    outputs: dict[str, str],
    sources: dict[str, Any],
    warned: int,
) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        url4 = _url4(recipe())

    assert context_of(url4, binding) == _context(outputs, sources)
    # WHY exactly the count of one pass: the second compile shares the first pass's warned set.
    assert sum(issubclass(item.category, sf.DuplicateMembersWarning) for item in caught) == warned


def test_a_corrective_round_claims_every_member_call_again() -> None:
    fusion = sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote(weights=_COST))
    loop = sf.CorrectiveLoop([fusion, "p/d"], judge="p/j", max_rounds=2)

    url4 = _url4(loop)

    assert "sources: {member_1: {}, member_2: {}}" in url4


def test_dotted_param_key_compiles_in_sources() -> None:
    model = sf.Model("p/a", params={"x.y": 1, "stop": "a:b/c"})
    url4 = _url4(sf.Fusion([model, "p/b"], synthesizer=sf.Vote(weights=_COST)))

    sources = {
        "member_1": {"model_1": _call("/p/a", "stop=a%3Ab%2Fc&x.y=1")},
        "member_2": {"model_2": _call("/p/b")},
    }
    assert context_of(url4, "synthesis_1") == _context(_AB, sources)


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Vote(),
        sf.Vote(weights=[1, 2, 3]),
        sf.Vote(weights=sf.signal("field:c")),
        sf.Median(),
        sf.Reduce("plurality", extract=sf.Extract("last_line", normalize="text")),
    ],
    ids=repr,
)
def test_existing_reducer_goldens_unchanged(synthesizer: Reducer) -> None:
    # SG#6 guard: a reducer that reads no accounting signal never gets `sources`.
    fusion = sf.Fusion(["p/a", "p/b", "p/c"], synthesizer=synthesizer)

    assert "sources:" not in _url4(fusion)


def test_a_fixture_reducer_gets_no_sources() -> None:
    fusion = sf.Fusion(["p/a", "p/b", "p/c"], synthesizer=FixtureVote())

    url4 = compile_candidate(fusion, operators=fixture_operators()).url4

    assert "sources:" not in url4
