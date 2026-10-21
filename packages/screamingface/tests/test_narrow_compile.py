"""The narrow compile: a block with narrow steps before its terminal (E4b surface unit 5).

FEATURE: ``Fanout >> [Judge] >> N1..Nk >> R`` compiles to ONE combine call whose spec has the
optional ``narrow`` list (narrow.md §2): one ``{extract, normalize, reduce, select}`` item per
narrow step, in chain order, before the main step of today. Two or more narrow steps before
``Synthesize`` make the last one the main selection and the others ``narrow`` (lowering §2.2).
STORY: as a researcher, ``Fanout(J) >> Filter(where=signal("field:confidence") > 0.7) >>
Mean(over="field:answer")`` runs as one call and averages only the confident members.
INVARIANT defended: a spec with no narrow step keeps its bytes (no ``narrow`` key); the main step
of a narrowed spec is the spec of today's form; a judge read by two steps is ONE judge call; the
carrier ``_narrow`` is private (no public signature, field or repr moves).
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import (
    ConcatNode,
    FilterNode,
    FusionNode,
    GateNode,
    JudgeNode,
    MeanNode,
    MedianNode,
    MergeNode,
    PickNode,
    RankNode,
    ReduceNode,
    VoteNode,
    frozen_url4,
)
from _vote_run_fixtures import spec_of
from url4 import build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import (
    accounting_signal,
    canonical_json,
    decode_combine_spec,
    spec_operator_pairs,
)
from screamingface._surface.chain import _Block
from screamingface._surface.lowering import lower
from screamingface.pipeline import Pipeline
from screamingface.reducer import Reducer, _narrowed
from screamingface.url4 import _calls, _candidate_expression

_JSON = "Reply with JSON: {'answer': <number>, 'confidence': <0..1>}."
_ROUTES = ["prov/alpha", "prov/beta", "prov/gamma"]
_JUDGE = "prov/judge"
_RUBRIC = "Score each draft from 0 to 10."


def _json_members() -> list[sf.Model]:
    return [sf.Model(route, prompt=_JSON) for route in _ROUTES]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _spec(recipe: sf.Recipe) -> dict[str, Any]:
    return dict(spec_of(_url4(recipe)))


def _without_narrow(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in spec.items() if key != "narrow"}


def _item(
    reduce: dict[str, Any],
    select: dict[str, Any],
    *,
    extract: dict[str, Any] | None = None,
    normalize: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"extract": extract, "normalize": normalize, "reduce": reduce, "select": select}


def _step(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"op": op, "args": {} if args is None else args}


def _judge() -> sf.Judge:
    return sf.Judge(_JUDGE, rubric=_RUBRIC)


def _combine_call(url4: str, binding: str = "synthesis_1") -> Any:
    candidate, _ = _candidate_expression(build(url4))
    return _calls(candidate)[binding]


def _judge_calls(url4: str) -> list[str]:
    candidate, _ = _candidate_expression(build(url4))
    return [name for name, call in _calls(candidate).items() if call.model == _JUDGE]


# ---------------------------------------------------------------- NC-1: the spec key


def test_nc1_filter_then_mean_writes_one_narrow_item() -> None:
    chain = (
        sf.Fanout(_json_members())
        >> sf.Filter(where=sf.signal("field:confidence") > 0.7)
        >> sf.Mean(over="field:answer")
    )
    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(
            _step("filter@1", {"key": "field:confidence", "cmp": "gt", "value": 0.7}),
            _step("kept@1"),
        )
    ]
    # the main step is the spec of today's form (the Fusion of the JSON members with
    # Reduce("mean") over the field answer), byte for byte
    assert _without_narrow(spec) == dict(spec_of(frozen_url4("narrow_compile:field-mean")))


def test_nc1_the_spec_text_stays_canonical() -> None:
    chain = (
        sf.Fanout(_json_members())
        >> sf.Filter(where=sf.signal("field:confidence") > 0.7)
        >> sf.Mean(over="field:answer")
    )

    raw = _combine_call(_url4(chain)).raw_intent

    assert raw == canonical_json(json.loads(raw))


def test_nc1_no_narrow_step_writes_no_key() -> None:
    chain = sf.Fanout(_json_members()) >> sf.Mean(over="field:answer")

    assert "narrow" not in _spec(chain)


def test_nc1_rank_then_vote_writes_a_by_signal_item() -> None:
    chain = (
        sf.Fanout(_json_members())
        >> sf.Rank(2, by="field:confidence")
        >> sf.Vote(over="field:answer")
    )
    # the same block with no narrow step (the parity tests tie it to today's bytes)
    plain = sf.Fanout(_json_members()) >> sf.Vote(over="field:answer")

    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(
            _step("by_signal@1", {"key": "field:confidence", "order": "max"}),
            _step("top_k@1", {"k": 2, "order": "max"}),
        )
    ]
    assert _without_narrow(spec) == _spec(plain)


def test_nc1_a_pattern_filter_keeps_its_extract() -> None:
    chain = sf.Fanout(_ROUTES) >> sf.Filter(where=sf.matches("^A"), over="last_line") >> sf.Vote()

    (item,) = _spec(chain)["narrow"]

    assert item["extract"] == _step("last_line@1")
    assert item["reduce"] == _step("filter@1", {"pattern": "^A"})
    assert item["select"] == _step("kept@1")


def test_nc1_a_judge_rank_writes_the_judge_scores_item() -> None:
    chain = sf.Fanout(_ROUTES) >> _judge() >> sf.Rank(2, by="score:judge") >> sf.Vote()

    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(_step("scores@1", {"source": "judge"}), _step("top_k@1", {"k": 2}))
    ]
    # the main vote reads no judge: it has no weights
    assert spec["weights"] is None


def test_nc1_narrow_steps_keep_their_chain_order() -> None:
    chain = (
        sf.Fanout(_json_members())
        >> sf.Filter(where=sf.signal("field:confidence") > 0.2)
        >> sf.Rank(2, by="field:confidence")
        >> sf.Median(over="field:answer", select="value")
    )

    narrow = _spec(chain)["narrow"]

    assert [item["reduce"]["op"] for item in narrow] == ["filter@1", "by_signal@1"]


def test_nc1_an_abstain_gate_after_a_narrow_step_compiles() -> None:
    gate = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> gate

    spec = _spec(chain)

    assert spec["gate"]["otherwise"] == "abstain"
    assert [item["reduce"]["op"] for item in spec["narrow"]] == ["by_signal@1"]


# ---------------------------------------------------------------- NC-2: narrow before a writer


def test_nc2_the_last_of_two_narrow_steps_is_the_main_selection() -> None:
    chain = (
        sf.Fanout(_ROUTES)
        >> sf.Rank(2, by="cost_usd")
        >> sf.Filter(where=sf.matches("x"))
        >> sf.Synthesize("prov/writer")
    )

    lowered = lower(chain)

    assert isinstance(lowered, Pipeline)
    fusion, writer = lowered._stage_values()
    assert isinstance(fusion, FusionNode)
    assert writer == sf.Model("prov/writer")
    assert isinstance(fusion.synthesizer, FilterNode)
    assert fusion.synthesizer._narrow == (RankNode(2, by_signal=sf.signal("cost_usd")),)
    spec = _spec(chain)
    assert (spec["reduce"], spec["select"]) == (
        _step("filter@1", {"pattern": "x"}),
        _step("kept@1"),
    )
    assert spec["narrow"] == [
        _item(
            _step("by_signal@1", {"key": "cost_usd", "order": "max"}),
            _step("top_k@1", {"k": 2, "order": "max"}),
        )
    ]


def test_nc2_a_concat_after_a_narrow_step_is_the_main_step() -> None:
    chain = (
        sf.Fanout(_ROUTES)
        >> sf.Rank(2, by="cost_usd")
        >> sf.Concat()
        >> sf.Synthesize("prov/writer")
    )

    spec = _spec(chain)

    assert spec["reducer"] == "concat"
    assert [item["reduce"]["op"] for item in spec["narrow"]] == ["by_signal@1"]


def test_nc2_one_narrow_step_before_a_writer_writes_no_narrow_key() -> None:
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> sf.Synthesize("prov/writer")

    assert "narrow" not in _spec(chain)


def test_nc2_a_narrow_accounting_read_puts_the_sources_in_the_context() -> None:
    # narrow §5: accounting_signal is true when ANY step reads an accounting key
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> sf.Vote()

    lowered = lower(chain)

    assert isinstance(lowered, FusionNode)
    assert isinstance(lowered.synthesizer, VoteNode)
    assert accounting_signal(lowered.synthesizer) == "cost_usd"
    assert "sources" in _combine_call(_url4(chain)).context


# ---------------------------------------------------------------- NC-3: one judge call


def test_nc3_a_judge_with_two_readers_is_one_call() -> None:
    chain = (
        sf.Fanout(_ROUTES)
        >> _judge()
        >> sf.Rank(2, by="score:judge")
        >> sf.Vote(weights="score:judge")
    )

    url4 = _url4(chain)

    assert len(_judge_calls(url4)) == 1
    spec: dict[str, Any] = dict(spec_of(url4))
    assert spec["weights"] == {"signal": "score:judge"}
    assert [item["reduce"] for item in spec["narrow"]] == [_step("scores@1", {"source": "judge"})]


def test_nc3_a_judge_read_only_by_a_narrow_step_is_one_call() -> None:
    chain = sf.Fanout(_ROUTES) >> _judge() >> sf.Rank(2, by="score:judge") >> sf.Vote()

    url4 = _url4(chain)

    assert len(_judge_calls(url4)) == 1
    assert "judge" in _combine_call(url4).context


def test_nc3_an_argmax_by_the_judge_after_a_filter_leaves_the_judge_step_as_it_is() -> None:
    judge = _judge()
    chain = (
        sf.Fanout(_ROUTES)
        >> judge
        >> sf.Filter(where=sf.signal("score:judge") >= 5)
        >> sf.ArgMax("score:judge")
    )

    lowered = lower(chain)

    assert isinstance(lowered, FusionNode)
    assert isinstance(lowered.synthesizer, JudgeNode)
    assert lowered.synthesizer._narrow != ()
    # the block's judge node is shared by its readers: the carrier is set on a copy
    assert judge._node._narrow == ()
    assert len(_judge_calls(_url4(chain))) == 1


# ---------------------------------------------------------------- the checks of every step


def test_a_narrow_step_that_reads_an_undeclared_name_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"reads sf\.signal\('p'\), which this sf\.Fanout does not"
    ):
        _ = sf.Fanout(_ROUTES) >> sf.Filter(where=sf.signal("p") > 0.5) >> sf.Vote()


def test_a_narrow_rank_over_the_member_count_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Rank keeps k=3 members but the sf\.Fanout has 2$"):
        _ = sf.Fanout(_ROUTES[:2]) >> sf.Rank(3, by="cost_usd") >> sf.Vote()


def test_a_declared_narrow_read_compiles() -> None:
    chain = (
        sf.Fanout(_ROUTES, signals={"p": sf.Verbalized("Confidence: ([0-9.]+)")})
        >> sf.Filter(where=sf.signal("p") >= 0.5)
        >> sf.Vote()
    )

    spec = _spec(chain)

    assert spec["narrow"][0]["reduce"] == _step("filter@1", {"key": "p", "cmp": "ge", "value": 0.5})
    assert set(spec["signals"]) == {"p"}


# ---------------------------------------------------------------- the url4 places (narrow §5)


def test_a_narrow_spec_decodes_and_names_its_narrow_operators() -> None:
    chain = (
        sf.Fanout(_json_members())
        >> sf.Filter(where=sf.signal("field:confidence") > 0.7)
        >> sf.Mean(over="field:answer")
    )
    raw = _combine_call(_url4(chain)).raw_intent

    pairs = spec_operator_pairs(decode_combine_spec(raw))

    assert ("reduce", "filter@1") in pairs
    assert ("select", "kept@1") in pairs
    assert ("reduce", "mean@1") in pairs


def test_to_python_of_a_narrow_url4_names_the_new_surface() -> None:
    # U5d lifted at the swap (7e): to_python writes the narrow step in the new surface
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> sf.Vote()

    assert sf.Url4(_url4(chain)).to_python().splitlines()[-3:] == [
        "    >> sf.Rank(2, by='cost_usd')",
        "    >> sf.Vote(over='last_line@1', normalize='text@1')",
        ")",
    ]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (('"op":"top_k@1"', '"op":"first_holder@1"'), "a vote spec"),
        (('"op":"top_k@1"', '"op":"kept@1"'), "a filter spec"),
    ],
    ids=["unknown-select", "scores-then-kept"],
)
def test_a_hand_edited_narrow_item_cannot_rebuild(edit: tuple[str, str], message: str) -> None:
    chain = sf.Fanout(_ROUTES) >> _judge() >> sf.Rank(2, by="score:judge") >> sf.Vote()
    url4 = _url4(chain)
    edited = url4.replace(*edit)
    assert edited != url4

    with pytest.raises(ValueError, match=rf"^URL4 Candidate has {message} this SDK version cannot"):
        sf.Url4(edited).to_python()


# ---------------------------------------------------------------- the carrier is private


def test_the_carrier_moves_no_public_signature_or_repr() -> None:
    for cls in (
        VoteNode,
        MedianNode,
        MeanNode,
        PickNode,
        JudgeNode,
        RankNode,
        FilterNode,
        ConcatNode,
    ):
        assert "_narrow" not in inspect.signature(cls).parameters
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> sf.Vote()
    lowered = lower(chain)

    assert isinstance(lowered, FusionNode)
    assert "_narrow" not in repr(lowered.synthesizer)
    assert VoteNode()._narrow == ()
    # a narrowed reducer is a different value from the same reducer with no narrow step
    assert lowered.synthesizer != VoteNode()


def test_the_block_record_keeps_its_narrow_steps() -> None:
    chain = sf.Fanout(_ROUTES) >> sf.Rank(2, by="cost_usd") >> sf.Vote()

    (block,) = chain._stages

    assert isinstance(block, _Block)
    assert block.narrow == (sf.Rank(2, by="cost_usd"),)


# ---------------------------------------------------------------- equality follows the bytes

_RANK = RankNode(2, by_signal=sf.signal("cost_usd"))


def _carriers() -> list[Reducer]:
    """One value of each of the nine reducer classes that carry narrow steps."""

    return [
        VoteNode(),
        MedianNode(),
        MeanNode(),
        ReduceNode("mean", extract=sf.Extract("field", path="answer")),
        PickNode(by_signal=sf.signal("cost_usd"), order="max"),
        JudgeNode(_JUDGE, returns="scores", rubric=_RUBRIC),
        RankNode(1, by_signal=sf.signal("latency_ms")),
        FilterNode(where=sf.matches("x")),
        ConcatNode(),
    ]


@pytest.mark.parametrize("plain", _carriers(), ids=lambda value: type(value).__name__)
def test_a_narrowed_value_differs_from_the_plain_one(plain: Reducer) -> None:
    narrowed = _narrowed(plain, (_RANK,))
    again = _narrowed(plain, (RankNode(2, by_signal=sf.signal("cost_usd")),))

    assert narrowed != plain
    assert plain != narrowed
    assert narrowed == again


def test_an_argmax_by_the_judge_after_a_narrow_step_is_not_the_plain_argmax() -> None:
    plain = lower(sf.Fanout(_ROUTES) >> _judge() >> sf.ArgMax("score:judge"))
    narrowed = lower(
        sf.Fanout(_ROUTES)
        >> _judge()
        >> sf.Filter(where=sf.signal("field:confidence") > 0.5)
        >> sf.ArgMax("score:judge")
    )

    assert isinstance(plain, FusionNode)
    assert isinstance(narrowed, FusionNode)
    assert narrowed.synthesizer != plain.synthesizer
    assert _url4(narrowed) != _url4(plain)


# ---------------------------------------------------------------- the carrier gate (NR-S1, NR-C1)

# A pattern filter: it reads no signal, so the context of the hand-edited url4 stays right.
_NARROW_ITEM = (
    '{"extract":null,"normalize":null,"reduce":{"args":{"pattern":"x"},"op":"filter@1"},'
    '"select":{"args":{},"op":"kept@1"}}'
)


def _with_narrow_items(url4: str, count: int) -> str:
    """``url4`` with ``count`` narrow items put into its one combine spec, by hand."""

    head, members, tail = url4.partition('"members":["member_1","member_2","member_3"],')
    assert members, "the url4 has no three-member combine spec"
    items = ",".join([_NARROW_ITEM] * count)
    return f'{head}{members}"narrow":[{items}],{tail}'


def _rebuild_refusal(url4: str, message: str) -> ValueError:
    with pytest.raises(ValueError, match=message) as caught:
        sf.Url4(url4).to_python()
    return caught.value


def test_the_rebuild_refuses_five_narrow_items() -> None:
    url4 = _url4(sf.Fanout(_ROUTES) >> sf.Vote())

    error = _rebuild_refusal(
        _with_narrow_items(url4, 5),
        r"^URL4 Candidate has a vote spec this SDK version cannot rebuild$",
    )

    assert str(error.__cause__) == "a combine call takes 1 to 4 narrow steps"


def test_the_rebuild_takes_four_narrow_items_as_far_as_to_python() -> None:
    url4 = _url4(sf.Fanout(_ROUTES) >> sf.Vote())

    # the url4 rebuilds and recompiles, and to_python spells the four narrow steps (7e)
    source = sf.Url4(_with_narrow_items(url4, 4)).to_python()

    assert source.count("    >> sf.Filter(where=sf.matches('x'))\n") == 4


def test_the_rebuild_refuses_a_label_judge_after_a_narrow_step() -> None:
    url4 = frozen_url4("narrow_compile:label-judge")  # today's Fusion of _ROUTES with a label judge

    error = _rebuild_refusal(
        _with_narrow_items(url4, 1),
        r"^URL4 Candidate has a judge spec this SDK version cannot rebuild$",
    )

    assert str(error.__cause__) == (
        "a label judge makes its own call over every member, so it cannot follow a narrow step"
    )


def test_the_rebuild_refuses_a_model_fallback_gate_after_a_narrow_step() -> None:
    # today's Fusion of _ROUTES with Vote(gate=Gate("agreement", ">=", 0.7, otherwise=writer))
    url4 = frozen_url4("narrow_compile:writer-gate")

    error = _rebuild_refusal(
        _with_narrow_items(url4, 1),
        r"^URL4 Candidate has a vote spec this SDK version cannot rebuild$",
    )

    assert str(error.__cause__) == (
        "a gate with a model fallback makes its own call over every member, so it cannot follow "
        "a narrow step"
    )


def test_an_abstain_gate_carries_narrow_steps() -> None:
    gate = GateNode("agreement", ">=", 0.7)

    assert _narrowed(VoteNode(gate=gate), (_RANK,))._narrow == (_RANK,)


def test_merge_cannot_carry_narrow_steps() -> None:
    merge = MergeNode(fields={"answer": sf.FieldRule.from_member(1)})

    with pytest.raises(ValueError, match=r"^sf\.Merge cannot follow a narrow step$"):
        _narrowed(merge, (_RANK,))
