"""A judge-weighted vote: sf.Vote(weights=sf.signal('score:judge'), judge=sf.Judge(...)) (OME-1289).

FEATURE (SR#11): the judge scores every member, and the vote weighs each answer by its member's
score. The Engine reads ``score:judge`` strictly, so the SDK pairs the weights with a scores judge
when the reducer is built, before any call is paid (8S F5).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from url4 import Expression, RelExpr, Source, Text, build, render, struct

import screamingface as sf
from screamingface._evaluation.candidate import _url4_text, compile_candidate
from screamingface.judge import judge_intent
from screamingface.reducer import Reducer

RUBRIC = "Score each answer."
SECRET = "SECRET-RUBRIC-TEXT"
JUDGE_SIGNAL = sf.signal("score:judge")
J = sf.Judge("provider/j", returns="scores", rubric=RUBRIC)
V = sf.Vote(extract="last_number", normalize="numeric", weights=JUDGE_SIGNAL, judge=J)
_NUMBER = sf.Extract("last_number", normalize="numeric")


def _compiled(recipe: sf.Recipe) -> Any:
    return compile_candidate(recipe, operators=flow_operators())


def _url4(synthesizer: Reducer) -> str:
    return _compiled(sf.Fusion(members3(), synthesizer=synthesizer)).url4


def _sources(url4: str) -> list[Any]:
    root = build(url4)
    assert isinstance(root, Expression)
    return list(root.sources)


def _by_name(url4: str) -> dict[str, RelExpr]:
    return {
        source.name: source.value
        for source in _sources(url4)
        if isinstance(source, Source)
        and source.name is not None
        and isinstance(source.value, RelExpr)
    }


def _outputs(first: int = 1) -> dict[str, str]:
    return {f"member_{index}": f"$model_{first + index - 1}" for index in (1, 2, 3)}


def test_vote_judge_scores_compile_the_judge_call_and_signals() -> None:
    compiled = _compiled(sf.Fusion(members3(), synthesizer=V))
    calls = _by_name(compiled.url4)

    assert [source.name for source in _sources(compiled.url4)] == [
        "model_1",
        "model_2",
        "model_3",
        "judge_1",
        "synthesis_1",
        "_sf_recipe",
    ]
    judge = calls["judge_1"]
    assert judge.path == "/provider/j"
    assert judge.params == (("binding", "judge_1"),)
    assert judge.context == render(struct({"input": "$input", "outputs": _outputs()}))
    assert isinstance(judge.intent, Text)
    assert judge.intent.value == _url4_text(judge_intent("scores", RUBRIC))
    combine = calls["synthesis_1"]
    assert combine.context == render(
        struct({"input": "$input", "outputs": _outputs(), "signals": {"judge": "$judge_1"}})
    )
    assert combine.context is not None
    assert "sources" not in combine.context
    assert isinstance(combine.intent, Text)
    spec = json.loads(combine.intent.value)
    assert spec["weights"] == {"signal": "score:judge"}
    assert (spec["reduce"]["op"], spec["select"]["op"]) == (
        "weighted_mode@1",
        "max_weight_holder@1",
    )
    assert [operation.kind for operation in compiled.operations] == [
        "model",
        "model",
        "model",
        "judge",
        "combine",
    ]
    assert compiled.operations[4].depends_on == (
        "op_model_1",
        "op_model_2",
        "op_model_3",
        "op_judge_1",
    )
    recipe = _sources(compiled.url4)[-1]
    assert isinstance(recipe.value, Text)
    synthesizer = json.loads(recipe.value.value)["recipe"]["synthesizer"]
    assert synthesizer["binding"] == "synthesis_1"
    assert (synthesizer["kind"], synthesizer["name"]) == ("reducer", "vote")
    assert [signal["key"] for signal in synthesizer["signals"]] == ["judge"]


def test_a_nested_vote_judge_call_is_never_a_claimant_of_the_outer_sources() -> None:
    inner = sf.Fusion(
        ["p/a", "p/b"],
        synthesizer=sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=JUDGE_SIGNAL,
            judge=sf.Judge("p/a", returns="scores", rubric=RUBRIC),
        ),
    )
    outer = sf.Fusion([inner, "p/c"], synthesizer=sf.Vote(weights=sf.signal("cost_usd")))

    url4 = _compiled(outer).url4

    sources = {
        "member_1": {
            "model_1": {"path": "/p/a", "params": ""},
            "model_2": {"path": "/p/b", "params": ""},
        },
        "member_2": {"model_3": {"path": "/p/c", "params": ""}},
    }
    assert _by_name(url4)["synthesis_2"].context == render(
        struct(
            {
                "input": "$input",
                "outputs": {"member_1": "$synthesis_1", "member_2": "$model_3"},
                "sources": sources,
            }
        )
    )
    assert _by_name(url4)["judge_1"].path == "/p/a"


@pytest.mark.parametrize("kind", ["vote", "block"])
def test_score_judge_weights_and_a_vote_judge_pair_up(kind: str) -> None:
    secret = sf.Judge("provider/j", returns="scores", rubric=SECRET)
    label = sf.Judge("provider/j", returns="label", rubric=SECRET)
    prefix = "Vote" if kind == "vote" else r"sf\.Reduce\('weighted'\)"
    read_only = rf"{prefix} judge is read only by weights=sf\.signal\('score:judge'\)"

    def make(weights: Any, judge: Any) -> Reducer:
        options: dict[str, Any] = {} if judge is None else {"judge": judge}
        if kind == "vote":
            return sf.Vote(weights=weights, **options)
        return sf.Reduce("weighted", extract=_NUMBER, weights=weights, **options)

    assert make(JUDGE_SIGNAL, secret) is not None  # the one valid pairing
    assert make(sf.signal("cost_usd"), None) is not None  # no judge, no pairing needed
    cases: list[tuple[Any, Any, type[Exception], str]] = [
        (JUDGE_SIGNAL, None, ValueError, r"needs a judge on the same reducer"),
        (
            JUDGE_SIGNAL,
            label,
            ValueError,
            rf"{prefix} judge needs sf\.Judge\(\.\.\., returns='scores'\)",
        ),
        ([1.0, 2.0, 3.0], secret, ValueError, read_only),
        (sf.signal("cost_usd"), secret, ValueError, read_only),
        (JUDGE_SIGNAL, "m", TypeError, r"must be an sf\.Judge"),
    ]
    if kind == "vote":
        cases.append((None, secret, ValueError, read_only))
    for weights, judge, error, message in cases:
        with pytest.raises(error, match=message) as caught:
            make(weights, judge)
        assert SECRET not in str(caught.value)


@pytest.mark.parametrize("normalize", ["numeric", "text"])
@pytest.mark.parametrize("rule", ["last_number", "boxed", "last_line"])
def test_weighted_judge_block_matches_vote(rule: Any, normalize: Any) -> None:
    vote = sf.Vote(extract=rule, normalize=normalize, weights=JUDGE_SIGNAL, judge=J)
    block = sf.Reduce(
        "weighted",
        extract=sf.Extract(rule, normalize=normalize),
        weights=JUDGE_SIGNAL,
        judge=J,
    )

    assert _url4(block) == _url4(vote)


def _exec_candidate(url4: str) -> Any:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    return namespace["candidate"]


def test_judge_weighted_vote_round_trips() -> None:
    url4 = _url4(V)

    code = sf.Url4(url4).to_python()
    assert (
        "sf.Vote(extract='last_number@1', normalize='numeric@1', "
        "weights=sf.signal('score:judge'), "
        "judge=sf.Judge('provider/j', returns='scores', rubric='Score each answer.'))"
    ) in code
    candidate = _exec_candidate(url4)
    assert type(candidate.synthesizer) is sf.Vote
    assert _compiled(candidate).url4 == url4


def test_the_regex_block_form_of_a_judge_weighted_vote_recovers_as_reduce() -> None:
    extract = sf.Extract("regex", normalize="text", pattern=r"Final: (\w+)", group=1)
    block = sf.Reduce("weighted", extract=extract, weights=JUDGE_SIGNAL, judge=J)
    url4 = _url4(block)

    candidate = _exec_candidate(url4)

    assert type(candidate.synthesizer) is sf.Reduce
    assert candidate.synthesizer == block
    assert _compiled(candidate).url4 == url4


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '"weights":{"signal":"score:judge"}',
            '"weights":{"signal":"cost_usd"}',
            "cannot rebuild",
        ),
        (
            "judge-template@1 returns=scores",
            "judge-template@1 returns=label",
            "unsupported judge call",
        ),
        (
            "signals: {judge: '$judge_1'}",
            "signals: {jury: '$judge_1'}",
            "does not match its model calls",
        ),
    ],
    ids=["weights", "template", "context-signals"],
)
def test_judge_weighted_vote_tampering_is_refused(old: str, new: str, message: str) -> None:
    url4 = _url4(V)
    assert old in url4

    with pytest.raises(ValueError, match=message):
        sf.Url4(url4.replace(old, new, 1)).to_python()


def test_judge_weighted_vote_topology_without_signals_is_refused() -> None:
    url4 = _url4(V)
    start = url4.index(',"signals":[')
    end = url4.index("}}]", start) + 3
    tampered = url4[:start] + url4[end:]

    with pytest.raises(ValueError, match="does not match its model calls"):
        sf.Url4(tampered).to_python()


def test_a_score_judge_spec_without_signals_cannot_be_rebuilt() -> None:
    from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec

    spec = decode_combine_spec(combine_spec_text(V, member_count=3, operators=flow_operators()))

    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Vote._from_spec(spec)
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Reduce._from_spec(spec)


def test_a_signals_spec_that_is_not_a_judge_weighted_vote_cannot_be_rebuilt() -> None:
    from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
    from screamingface.judge import judge_from_signals

    plain = decode_combine_spec(
        combine_spec_text(sf.Vote(), member_count=3, operators=flow_operators())
    )
    signals = V._plan().signal_calls

    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Reduce._rebuild(plain, signals)
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Vote._rebuild(plain, signals)
    assert judge_from_signals(signals, "scores") == J


def test_vote_repr_python_and_equality_carry_the_judge() -> None:
    expected_judge = "Judge('provider/j', returns='scores', rubric='Score each answer.')"

    assert repr(V).endswith(f", judge={expected_judge})")
    namespace = {"Vote": sf.Vote, "Judge": sf.Judge, "signal": sf.signal}
    assert eval(repr(V), namespace) == V  # noqa: S307 - the repr is the contract
    assert V._python().endswith(f", judge=sf.{expected_judge})")
    assert V != sf.Vote(
        extract="last_number",
        normalize="numeric",
        weights=JUDGE_SIGNAL,
        judge=sf.Judge("provider/j", returns="scores", rubric="Another rubric."),
    )
    assert V.judge == J
    assert sf.Vote().judge is None
