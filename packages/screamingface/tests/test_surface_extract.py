"""The ``over=`` extractor of ``sf.Vote``, ``sf.Median`` and ``sf.Mean`` (E4b surface unit 2, §9).

FEATURE: ``over=`` takes a rule name (``"last_line"``), the same name with a pinned version
(``"last_line@1"``), ``"field:<path>"`` (the JSON field text), or ``sf.Extract(rule, ...)``. A
rule name lowers to today's named reducer; a field or an ``sf.Extract`` lowers to today's block
form (lowering §2.2). Any other string is refused with the list of rule names (EX-1). A
normalizer on both the step and the ``sf.Extract`` is refused (EX-2).
STORY: as a researcher, I say which part of each answer the reducer reads, in one argument.
"""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import FusionNode, MeanNode, MedianNode, ReduceNode, VoteNode

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower

_TRIO = ["provider/a", "provider/b", "provider/c"]
_RULES = "boxed, last_number, last_line, whole, json, benchmark, inspect_number, inspect_aime"


def _synthesizer(step: object) -> object:
    node = lower(sx.Fanout(_TRIO) >> step)  # type: ignore[operator]
    assert isinstance(node, FusionNode)
    return node.synthesizer


# ---------------------------------------------------------------- rule names


@pytest.mark.parametrize(
    "rule", ["last_line", "last_number", "boxed", "whole", "inspect_number", "inspect_aime"]
)
def test_a_rule_name_lowers_to_the_named_vote(rule: str) -> None:
    assert _synthesizer(sx.Vote(over=rule)) == VoteNode(extract=rule)


@pytest.mark.parametrize("rule", ["last_line@1", "last_number@1", "boxed@2"])
def test_a_pinned_rule_name_lowers_to_the_named_vote(rule: str) -> None:
    assert _synthesizer(sx.Vote(over=rule, normalize="text@1")) == VoteNode(
        extract=rule, normalize="text@1"
    )


def test_the_json_rule_lowers_to_its_engine_operator() -> None:
    assert _synthesizer(sx.Vote(over="json")) == VoteNode(extract="json_object")
    assert _synthesizer(sx.Vote(over="json@1")) == VoteNode(extract="json_object@1")


def test_the_benchmark_rule_lowers_to_the_benchmark_vote() -> None:
    assert _synthesizer(sx.Vote(over="benchmark")) == VoteNode(extract="benchmark")


def test_median_and_mean_take_a_rule_name() -> None:
    assert _synthesizer(sx.Median(over="boxed", select="value")) == MedianNode(
        extract="boxed", select="value"
    )
    assert _synthesizer(sx.Mean(over="last_number@1")) == MeanNode(extract="last_number@1")


@pytest.mark.parametrize(
    "over",
    ["last_word", "regex", "field", "Last_Line", "last_line@0", "last_line@v1", "", "json_object"],
)
def test_ex1_any_other_string_is_refused_with_the_rule_names(over: str) -> None:
    message = (
        rf"^over= must be a rule name \({_RULES}\), a rule name with a version such as "
        rf"'last_line@1', 'field:<path>', or sf\.Extract\(\.\.\.\), not {over!r}$"
    )
    for step in (sx.Vote, sx.Median, sx.Mean):
        with pytest.raises(ValueError, match=message):
            step(over=over)


def test_ex1_a_value_that_is_not_text_or_an_extract_is_refused() -> None:
    with pytest.raises(TypeError, match=r"^over= must be a rule name or sf\.Extract\(\.\.\.\)$"):
        sx.Vote(over=3)  # type: ignore[arg-type]


# ---------------------------------------------------------------- "field:<path>"


def test_a_field_vote_lowers_to_the_plurality_block_with_the_text_normalizer() -> None:
    assert _synthesizer(sx.Vote(over="field:answer")) == ReduceNode(
        "plurality", extract=sf.Extract("field", normalize="text", path="answer")
    )


def test_a_field_vote_takes_the_passed_normalizer() -> None:
    assert _synthesizer(sx.Vote(over="field:a.b[0]", normalize="numeric")) == ReduceNode(
        "plurality", extract=sf.Extract("field", normalize="numeric", path="a.b[0]")
    )
    assert _synthesizer(sx.Vote(over="field:answer", normalize=None)) == ReduceNode(
        "plurality", extract=sf.Extract("field", path="answer")
    )


def test_a_weighted_field_vote_lowers_to_the_weighted_block() -> None:
    assert _synthesizer(sx.Vote(over="field:answer", weights="field:confidence")) == ReduceNode(
        "weighted",
        extract=sf.Extract("field", normalize="text", path="answer"),
        weights=sf.signal("field:confidence"),
    )
    assert _synthesizer(sx.Vote(over="field:answer", weights=(1, 2, 3))) == ReduceNode(
        "weighted",
        extract=sf.Extract("field", normalize="text", path="answer"),
        weights=(1, 2, 3),
    )


def test_a_field_median_and_mean_lower_to_the_numeric_block() -> None:
    assert _synthesizer(sx.Median(over="field:answer")) == ReduceNode(
        "median", extract=sf.Extract("field", path="answer")
    )
    assert _synthesizer(sx.Mean(over="field:answer", weights="field:confidence")) == ReduceNode(
        "mean", extract=sf.Extract("field", path="answer"), weights=sf.signal("field:confidence")
    )
    assert _synthesizer(sx.Median(over="field:answer", select="value")) == ReduceNode(
        "median", mode="compute", extract=sf.Extract("field", path="answer")
    )


@pytest.mark.parametrize("over", ["field:", "field:a..b", "field:1a", "field:a b"])
def test_a_field_with_a_bad_path_is_refused(over: str) -> None:
    message = (
        rf"^over={over!r} must name a JSON path after 'field:', like 'field:a\.b' or "
        r"'field:a\[0\]\.b'$"
    )
    with pytest.raises(ValueError, match=message):
        sx.Vote(over=over)


# ---------------------------------------------------------------- sf.Extract


def test_an_extract_vote_lowers_to_the_block_with_the_extract_normalizer() -> None:
    extract = sf.Extract("regex", normalize="text", pattern="Answer: (.*)")

    assert _synthesizer(sx.Vote(over=extract)) == ReduceNode("plurality", extract=extract)


def test_an_extract_with_no_normalizer_has_none_unless_the_step_passes_one() -> None:
    extract = sf.Extract("regex", pattern="Answer: (.*)")

    assert _synthesizer(sx.Vote(over=extract)) == ReduceNode("plurality", extract=extract)
    assert _synthesizer(sx.Vote(over=extract, normalize="set")) == ReduceNode(
        "plurality", extract=sf.Extract("regex", normalize="set", pattern="Answer: (.*)")
    )


def test_an_extract_mean_lowers_to_the_numeric_block() -> None:
    extract = sf.Extract("regex", pattern="([0-9]+)")

    assert _synthesizer(sx.Mean(over=extract, select="nearest")) == ReduceNode(
        "mean", mode="select", extract=extract
    )


@pytest.mark.parametrize("normalize", ["text", None, "text@1"])
def test_ex2_a_normalizer_on_both_the_step_and_the_extract_is_refused(
    normalize: str | None,
) -> None:
    extract = sf.Extract("regex", normalize="text", pattern="Answer: (.*)")

    with pytest.raises(
        ValueError, match=r"^set normalize on sf\.Extract or on the step, not on both$"
    ):
        sx.Vote(over=extract, normalize=normalize)


def test_ex2_the_default_normalizer_is_not_a_conflict() -> None:
    extract = sf.Extract("regex", normalize="numeric", pattern="([0-9]+)")

    vote = sx.Vote(over=extract)
    assert vote.over == sf.Extract("regex", pattern="([0-9]+)")
    assert vote.normalize == "numeric"


# ---------------------------------------------------------------- weights


def test_a_weights_key_string_is_a_signal() -> None:
    assert _synthesizer(sx.Vote(weights="cost_usd")) == VoteNode(weights=sf.signal("cost_usd"))
    assert _synthesizer(sx.Median(weights="field:confidence")) == MedianNode(
        weights=sf.signal("field:confidence")
    )
    assert sx.Vote(weights=sf.signal("cost_usd")) == sx.Vote(weights="cost_usd")


def test_a_bad_weights_key_has_the_signal_message() -> None:
    with pytest.raises(ValueError) as from_string:
        sx.Vote(weights="score:other")
    with pytest.raises(ValueError) as from_signal:
        sf.signal("score:other")

    assert str(from_string.value) == str(from_signal.value)


def test_median_and_mean_refuse_a_judge_weight_with_the_rule_of_today() -> None:
    with pytest.raises(ValueError, match=r"Median cannot read sf\.signal\('score:judge'\)"):
        sx.Median(weights="score:judge")
    with pytest.raises(ValueError, match=r"Mean cannot read sf\.signal\('score:judge'\)"):
        sx.Mean(weights="score:judge")


def test_vote_verify_takes_only_none() -> None:
    with pytest.raises(ValueError, match="verify= is reserved"):
        sx.Vote(verify=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------- equal values, equal bytes

_LAST_LINE = sf.Extract("last_line")
_LAST_LINE_TEXT = sf.Extract("last_line", normalize="text")


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        (sx.Vote(), sx.Vote(normalize="text"), True),
        (sx.Vote(), sx.Vote(normalize=None), False),
        (sx.Vote(over="field:a"), sx.Vote(over="field:a", normalize="text"), True),
        (sx.Vote(over="field:a"), sx.Vote(over="field:a", normalize=None), False),
        (sx.Vote(over=_LAST_LINE_TEXT), sx.Vote(over=_LAST_LINE, normalize="text"), True),
        (sx.Vote(over=_LAST_LINE), sx.Vote(over=_LAST_LINE, normalize=None), True),
        (sx.Vote(over=_LAST_LINE), sx.Vote(over=_LAST_LINE, normalize="text"), False),
        (sx.Vote(over=_LAST_LINE), sx.Vote(over=_LAST_LINE_TEXT), False),
    ],
    ids=[
        "rule-default-text",
        "rule-none",
        "field-default-text",
        "field-none",
        "extract-text-either-place",
        "extract-none-either-way",
        "extract-default-is-none",
        "extract-text-vs-none",
    ],
)
def test_equal_votes_compile_to_equal_bytes(first: sx.Vote, second: sx.Vote, same: bool) -> None:
    def url4(vote: sx.Vote) -> str:
        chain = sx.Fanout(_TRIO) >> vote
        return compile_candidate(chain, operators=flow_operators()).url4

    assert (first == second) is same
    assert (url4(first) == url4(second)) is same


def test_a_pinned_benchmark_rule_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^over='benchmark' names the benchmark's answer rule and takes no version$",
    ):
        sx.Vote(over="benchmark@1")


def test_the_benchmark_rule_takes_no_normalizer() -> None:
    with pytest.raises(
        ValueError,
        match=r"^over='benchmark' takes the benchmark's own normalizer: leave out normalize=$",
    ):
        sx.Vote(over="benchmark", normalize="text")


def test_a_judge_weighted_vote_checks_its_other_options_when_it_is_built() -> None:
    with pytest.raises(TypeError):
        sx.Vote(weights="score:judge", normalize=3)  # type: ignore[arg-type]


def test_a_numeric_extract_holds_no_normalizer_of_its_own() -> None:
    plain = sx.Median(over=sf.Extract("regex", pattern="([0-9]+)"))
    numeric = sx.Median(over=sf.Extract("regex", normalize="numeric", pattern="([0-9]+)"))

    assert plain == numeric
    assert _synthesizer(plain) == _synthesizer(numeric)


def test_a_numeric_extract_with_another_normalizer_is_refused() -> None:
    message = r"^sf\.Mean reads numbers, so its sf\.Extract takes normalize='numeric' or none$"
    with pytest.raises(ValueError, match=message):
        sx.Mean(over=sf.Extract("regex", normalize="text", pattern="([0-9]+)"))
