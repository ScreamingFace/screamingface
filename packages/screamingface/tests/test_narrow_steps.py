"""The narrow steps ``Rank``, ``Filter`` and ``Concat`` (E4b surface unit 3, surface §5).

FEATURE: a narrow step makes the panel smaller and never ends a block. ``Rank(k, *, by,
order="max")`` keeps the ``k`` members with the highest or lowest value of one signal;
``Filter(*, where, over=None)`` keeps the members that pass a test; ``Concat`` joins the members
for a ``Synthesize``. A key ``"field:<path>"`` reads the field as a number signal (RE-1).
INVARIANT (NR-C1): ``Merge`` and ``JudgePick`` make their own call over every member, so a narrow
step before them is refused.
"""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower

_TRIO = ["provider/a", "provider/b", "provider/c"]
_WRITER = "provider/w"


def _narrowed(step: object) -> sf.Recipe:
    return lower(sx.Fanout(_TRIO) >> step >> sx.Synthesize(_WRITER))  # type: ignore[operator]


def _today(synthesizer: sf.Recipe | object) -> sf.Recipe:
    return sf.Pipeline([sf.Fusion(_TRIO, synthesizer=synthesizer), _WRITER])  # type: ignore[arg-type]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


# ---------------------------------------------------------------- Rank


def test_rank_by_a_key_string_lowers_to_the_rank_by_signal() -> None:
    assert _narrowed(sx.Rank(2, by="cost_usd", order="min")) == _today(
        sf.Rank(k=2, by_signal=sf.signal("cost_usd"), order="min")
    )
    assert sx.Rank(2, by="cost_usd") == sx.Rank(2, by=sf.signal("cost_usd"))


@pytest.mark.parametrize(
    "by",
    [sf.Judge("provider/j", returns="scores", rubric="r"), 3, None],
    ids=["judge", "number", "none"],
)
def test_ra1_by_must_be_one_signal(by: object) -> None:
    with pytest.raises(
        TypeError,
        match=r"^sf\.Rank by= must be one signal: a key string such as 'cost_usd' or "
        r"sf\.signal\(key\)$",
    ):
        sx.Rank(2, by=by)  # type: ignore[arg-type]


def test_a_bad_rank_key_has_the_signal_message() -> None:
    with pytest.raises(ValueError) as from_string:
        sx.Rank(2, by="score:other")
    with pytest.raises(ValueError) as from_signal:
        sf.signal("score:other")

    assert str(from_string.value) == str(from_signal.value)


@pytest.mark.parametrize(
    ("k", "order", "error", "message"),
    [
        (0, "max", ValueError, "Rank k must be between 1 and 256"),
        (True, "max", TypeError, "Rank k must be an integer"),
        (2, "best", ValueError, "Rank order must be 'max' or 'min'"),
    ],
    ids=["k-zero", "k-bool", "order"],
)
def test_rank_checks_k_and_order_with_the_rules_of_today(
    k: int, order: str, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        sx.Rank(k, by="cost_usd", order=order)  # type: ignore[arg-type]


def test_rank_k_above_the_member_count_raises_at_block_close() -> None:
    rank = sx.Rank(4, by="cost_usd")

    with pytest.raises(ValueError, match="Rank keeps k=4 members but the Fusion has 3"):
        _ = sx.Fanout(_TRIO) >> rank >> sx.Synthesize(_WRITER)


# ---------------------------------------------------------------- RE-1


def test_re1_a_field_key_reads_the_field_as_a_number_signal() -> None:
    assert _url4(
        sx.Fanout(_TRIO) >> sx.Rank(2, by="field:confidence") >> sx.Synthesize(_WRITER)
    ) == (_url4(_today(sf.Rank(k=2, by_signal=sf.signal("field:confidence")))))
    assert _url4(sx.Fanout(_TRIO) >> sx.ArgMax("field:confidence")) == _url4(
        sf.Fusion(_TRIO, synthesizer=sf.Pick(by_signal=sf.signal("field:confidence")))
    )


# ---------------------------------------------------------------- Filter


def test_filter_by_a_signal_comparison() -> None:
    where = sf.signal("field:confidence") > 0.7

    assert _narrowed(sx.Filter(where=where)) == _today(sf.Filter(where=where))


@pytest.mark.parametrize(
    ("over", "extract"),
    [
        ("last_line", sf.Extract("last_line")),
        ("field:answer", sf.Extract("field", path="answer")),
        (sf.Extract("regex", pattern="A: (.*)"), sf.Extract("regex", pattern="A: (.*)")),
    ],
    ids=["rule", "field", "extract"],
)
def test_filter_over_reads_the_text_that_matches_tests(over: object, extract: sf.Extract) -> None:
    where = sf.matches("yes")

    assert _narrowed(sx.Filter(where=where, over=over)) == _today(  # type: ignore[arg-type]
        sf.Filter(where=where, extract=extract)
    )
    assert sx.Filter(where=where, over=over) == sx.Filter(where=where, over=extract)  # type: ignore[arg-type]


def test_fi1_over_with_a_signal_comparison_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.Filter over= reads the text for sf\.matches: a signal comparison takes no "
        r"over=$",
    ):
        sx.Filter(where=sf.signal("cost_usd") < 1, over="last_line")


def test_filter_over_takes_no_pinned_rule_name() -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.Filter over= takes a rule name with no version, 'field:<path>' or "
        r"sf\.Extract\(\.\.\.\), not 'last_line@1'$",
    ):
        sx.Filter(where=sf.matches("yes"), over="last_line@1")


@pytest.mark.parametrize("where", ["cost_usd", sf.signal("cost_usd"), 3])
def test_filter_where_takes_only_a_condition(where: object) -> None:
    with pytest.raises(
        TypeError,
        match=r"^sf\.Filter where= takes sf\.matches\(\.\.\.\) or a signal comparison such as "
        r"sf\.signal\(key\) >= 0\.6$",
    ):
        sx.Filter(where=where)  # type: ignore[arg-type]


# ---------------------------------------------------------------- Concat


def test_concat_lowers_to_the_concat_of_today() -> None:
    assert _narrowed(sx.Concat(" | ", label=False)) == _today(sf.Concat(" | ", label=False))
    assert sx.Concat() == sx.Concat("\n\n---\n\n", label=True)


def test_concat_checks_its_options_with_the_rules_of_today() -> None:
    with pytest.raises(ValueError, match="Concat separator must not be empty"):
        sx.Concat("")
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sx.Concat(label=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------- NR-C1 (Merge, JudgePick)


@pytest.mark.parametrize(
    "terminal",
    [
        sx.Merge({"answer": sf.FieldRule.majority()}),
        sx.JudgePick("provider/j", rubric="Pick one."),
    ],
    ids=["merge", "judge-pick"],
)
@pytest.mark.parametrize(
    "narrow",
    [sx.Rank(1, by="cost_usd"), sx.Filter(where=sf.matches("x"))],
    ids=["rank", "filter"],
)
def test_nrc1_a_step_with_its_own_call_cannot_follow_a_narrow_step(
    narrow: sx.Rank, terminal: sx.Merge
) -> None:
    name = type(terminal).__name__
    with pytest.raises(
        ValueError,
        match=rf"^sf\.{name} makes its own call over every member, so it cannot follow a "
        r"narrow step$",
    ):
        _ = sx.Fanout(_TRIO) >> narrow >> terminal


# ---------------------------------------------------------------- E4 (FA-2 with a narrow step)


def test_e4_signals_with_a_narrow_step_before_synthesize_are_read() -> None:
    signals = {"conf": sf.Verbalized("C: ([0-9]+)")}
    chain = sx.Fanout(_TRIO, signals=signals) >> sx.Rank(2, by="conf") >> sx.Synthesize(_WRITER)

    assert lower(chain) == sf.Pipeline(
        [
            sf.Fusion(
                _TRIO, signals=signals, synthesizer=sf.Rank(k=2, by_signal=sf.signal("conf"))
            ),
            _WRITER,
        ]
    )


def test_a_filter_stores_a_plain_signal() -> None:
    from screamingface._signals import Signal, _Comparison

    step = sx.Filter(where=sx.signal("field:confidence") > 0.7)
    node = _narrowed(step)

    assert isinstance(step.where, _Comparison)
    assert type(step.where.signal) is Signal
    assert isinstance(node, sf.Pipeline)
    fusion = node.stages[0]
    assert isinstance(fusion, sf.Fusion)
    synthesizer = fusion.synthesizer
    assert isinstance(synthesizer, sf.Filter)
    assert isinstance(synthesizer.where, _Comparison)
    assert type(synthesizer.where.signal) is Signal
