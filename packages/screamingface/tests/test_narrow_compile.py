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
from _vote_run_fixtures import spec_of
from url4 import build

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import (
    accounting_signal,
    canonical_json,
    decode_combine_spec,
    spec_operator_pairs,
)
from screamingface._surface.chain import _Block
from screamingface._surface.lowering import lower
from screamingface.fusion import Fusion
from screamingface.pipeline import Pipeline
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


def _judge() -> sx.Judge:
    return sx.Judge(_JUDGE, rubric=_RUBRIC)


def _combine_call(url4: str, binding: str = "synthesis_1") -> Any:
    candidate, _ = _candidate_expression(build(url4))
    return _calls(candidate)[binding]


def _judge_calls(url4: str) -> list[str]:
    candidate, _ = _candidate_expression(build(url4))
    return [name for name, call in _calls(candidate).items() if call.model == _JUDGE]


# ---------------------------------------------------------------- NC-1: the spec key


def test_nc1_filter_then_mean_writes_one_narrow_item() -> None:
    chain = (
        sx.Fanout(_json_members())
        >> sx.Filter(where=sx.signal("field:confidence") > 0.7)
        >> sx.Mean(over="field:answer")
    )
    today = sf.Fusion(
        _json_members(),
        synthesizer=sf.Reduce("mean", extract=sf.Extract("field", path="answer")),
    )

    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(
            _step("filter@1", {"key": "field:confidence", "cmp": ">", "value": 0.7}),
            _step("kept@1"),
        )
    ]
    # the main step is the spec of today's form, byte for byte
    assert _without_narrow(spec) == _spec(today)


def test_nc1_the_spec_text_stays_canonical() -> None:
    chain = (
        sx.Fanout(_json_members())
        >> sx.Filter(where=sx.signal("field:confidence") > 0.7)
        >> sx.Mean(over="field:answer")
    )

    raw = _combine_call(_url4(chain)).raw_intent

    assert raw == canonical_json(json.loads(raw))


def test_nc1_no_narrow_step_writes_no_key() -> None:
    chain = sx.Fanout(_json_members()) >> sx.Mean(over="field:answer")

    assert "narrow" not in _spec(chain)


def test_nc1_rank_then_vote_writes_a_by_signal_item() -> None:
    chain = (
        sx.Fanout(_json_members())
        >> sx.Rank(2, by="field:confidence")
        >> sx.Vote(over="field:answer")
    )
    today = sf.Fusion(
        _json_members(),
        synthesizer=sf.Reduce("plurality", extract=sf.Extract("field", path="answer")),
    )

    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(
            _step("by_signal@1", {"key": "field:confidence", "order": "max"}),
            _step("top_k@1", {"k": 2, "order": "max"}),
        )
    ]
    assert _without_narrow(spec) == _spec(today)


def test_nc1_a_pattern_filter_keeps_its_extract() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Filter(where=sx.matches("^A"), over="last_line") >> sx.Vote()

    (item,) = _spec(chain)["narrow"]

    assert item["extract"] == _step("last_line@1")
    assert item["reduce"] == _step("filter@1", {"pattern": "^A"})
    assert item["select"] == _step("kept@1")


def test_nc1_a_judge_rank_writes_the_judge_scores_item() -> None:
    chain = sx.Fanout(_ROUTES) >> _judge() >> sx.Rank(2, by="score:judge") >> sx.Vote()

    spec = _spec(chain)

    assert spec["narrow"] == [
        _item(_step("scores@1", {"source": "judge"}), _step("top_k@1", {"k": 2}))
    ]
    # the main vote reads no judge: it has no weights
    assert spec["weights"] is None


def test_nc1_narrow_steps_keep_their_chain_order() -> None:
    chain = (
        sx.Fanout(_json_members())
        >> sx.Filter(where=sx.signal("field:confidence") > 0.2)
        >> sx.Rank(2, by="field:confidence")
        >> sx.Median(over="field:answer", select="value")
    )

    narrow = _spec(chain)["narrow"]

    assert [item["reduce"]["op"] for item in narrow] == ["filter@1", "by_signal@1"]


def test_nc1_an_abstain_gate_after_a_narrow_step_compiles() -> None:
    gate = sx.Gate(when=sx.agreement() >= 0.7, then=sx.Vote())
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> gate

    spec = _spec(chain)

    assert spec["gate"]["otherwise"] == "abstain"
    assert [item["reduce"]["op"] for item in spec["narrow"]] == ["by_signal@1"]


# ---------------------------------------------------------------- NC-2: narrow before a writer


def test_nc2_the_last_of_two_narrow_steps_is_the_main_selection() -> None:
    chain = (
        sx.Fanout(_ROUTES)
        >> sx.Rank(2, by="cost_usd")
        >> sx.Filter(where=sx.matches("x"))
        >> sx.Synthesize("prov/writer")
    )

    lowered = lower(chain)

    assert isinstance(lowered, Pipeline)
    fusion, writer = lowered.stages
    assert isinstance(fusion, Fusion)
    assert writer == sf.Model("prov/writer")
    assert isinstance(fusion.synthesizer, sf.Filter)
    assert fusion.synthesizer._narrow == (sf.Rank(2, by_signal=sf.signal("cost_usd")),)
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
        sx.Fanout(_ROUTES)
        >> sx.Rank(2, by="cost_usd")
        >> sx.Concat()
        >> sx.Synthesize("prov/writer")
    )

    spec = _spec(chain)

    assert spec["reducer"] == "concat"
    assert [item["reduce"]["op"] for item in spec["narrow"]] == ["by_signal@1"]


def test_nc2_one_narrow_step_before_a_writer_writes_no_narrow_key() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> sx.Synthesize("prov/writer")

    assert "narrow" not in _spec(chain)


def test_nc2_a_narrow_accounting_read_puts_the_sources_in_the_context() -> None:
    # narrow §5: accounting_signal is true when ANY step reads an accounting key
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> sx.Vote()

    lowered = lower(chain)

    assert isinstance(lowered, Fusion)
    assert isinstance(lowered.synthesizer, sf.Vote)
    assert accounting_signal(lowered.synthesizer) == "cost_usd"
    assert "sources" in _combine_call(_url4(chain)).context


# ---------------------------------------------------------------- NC-3: one judge call


def test_nc3_a_judge_with_two_readers_is_one_call() -> None:
    chain = (
        sx.Fanout(_ROUTES)
        >> _judge()
        >> sx.Rank(2, by="score:judge")
        >> sx.Vote(weights="score:judge")
    )

    url4 = _url4(chain)

    assert len(_judge_calls(url4)) == 1
    spec = spec_of(url4)
    assert spec["weights"] == {"signal": "score:judge"}
    assert [item["reduce"] for item in spec["narrow"]] == [_step("scores@1", {"source": "judge"})]


def test_nc3_a_judge_read_only_by_a_narrow_step_is_one_call() -> None:
    chain = sx.Fanout(_ROUTES) >> _judge() >> sx.Rank(2, by="score:judge") >> sx.Vote()

    url4 = _url4(chain)

    assert len(_judge_calls(url4)) == 1
    assert "judge" in _combine_call(url4).context


def test_nc3_a_judge_pick_after_a_filter_leaves_the_judge_step_as_it_is() -> None:
    judge = _judge()
    chain = (
        sx.Fanout(_ROUTES)
        >> judge
        >> sx.Filter(where=sx.signal("score:judge") >= 5)
        >> sx.ArgMax("score:judge")
    )

    lowered = lower(chain)

    assert isinstance(lowered, Fusion)
    assert lowered.synthesizer._narrow != ()
    # the block's judge node is shared by its readers: the carrier is set on a copy
    assert judge._node._narrow == ()
    assert len(_judge_calls(_url4(chain))) == 1


# ---------------------------------------------------------------- the checks of every step


def test_a_narrow_step_that_reads_an_undeclared_name_is_refused() -> None:
    with pytest.raises(ValueError, match=r"reads sf\.signal\('p'\), which this Fusion does not"):
        _ = sx.Fanout(_ROUTES) >> sx.Filter(where=sx.signal("p") > 0.5) >> sx.Vote()


def test_a_narrow_rank_over_the_member_count_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^Rank keeps k=3 members but the Fusion has 2$"):
        _ = sx.Fanout(_ROUTES[:2]) >> sx.Rank(3, by="cost_usd") >> sx.Vote()


def test_a_declared_narrow_read_compiles() -> None:
    chain = (
        sx.Fanout(_ROUTES, signals={"p": sf.Verbalized()})
        >> sx.Filter(where=sx.signal("p") >= 0.5)
        >> sx.Vote()
    )

    spec = _spec(chain)

    assert spec["narrow"][0]["reduce"] == _step("filter@1", {"key": "p", "cmp": ">=", "value": 0.5})
    assert set(spec["signals"]) == {"p"}


# ---------------------------------------------------------------- the url4 places (narrow §5)


def test_a_narrow_spec_decodes_and_names_its_narrow_operators() -> None:
    chain = (
        sx.Fanout(_json_members())
        >> sx.Filter(where=sx.signal("field:confidence") > 0.7)
        >> sx.Mean(over="field:answer")
    )
    raw = _combine_call(_url4(chain)).raw_intent

    pairs = spec_operator_pairs(decode_combine_spec(raw))

    assert ("reduce", "filter@1") in pairs
    assert ("select", "kept@1") in pairs
    assert ("reduce", "mean@1") in pairs


def test_to_python_of_a_narrow_url4_names_the_new_surface() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> sx.Vote()

    with pytest.raises(ValueError, match=r"narrow steps"):
        sf.Url4(_url4(chain)).to_python()


# ---------------------------------------------------------------- the carrier is private


def test_the_carrier_moves_no_public_signature_or_repr() -> None:
    for cls in (sf.Vote, sf.Median, sf.Mean, sf.Pick, sf.Judge, sf.Rank, sf.Filter, sf.Concat):
        assert "_narrow" not in inspect.signature(cls).parameters
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> sx.Vote()
    lowered = lower(chain)

    assert isinstance(lowered, Fusion)
    assert "_narrow" not in repr(lowered.synthesizer)
    assert sf.Vote()._narrow == ()
    # a narrowed reducer is a different value from the same reducer with no narrow step
    assert lowered.synthesizer != sf.Vote()


def test_the_block_record_keeps_its_narrow_steps() -> None:
    chain = sx.Fanout(_ROUTES) >> sx.Rank(2, by="cost_usd") >> sx.Vote()

    (block,) = chain._stages

    assert isinstance(block, _Block)
    assert block.narrow == (sx.Rank(2, by="cost_usd"),)
