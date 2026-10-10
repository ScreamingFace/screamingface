"""sf.Rank by a named signal, and the top_k block form (OME-1289 gap, SR#9, BK#4).

FEATURE: ``sf.Rank(k, by_signal=sf.signal(key), order="max"|"min")`` keeps the k members with the
highest or lowest value of a named number on each Answer.
INVARIANT (10E F3): the SAME order goes in ``by_signal@1`` and in ``top_k@1``; the Engine does not
cross-check them, and the select step's order decides which members are kept.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from url4 import Expression, RelExpr, Source, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer

_KEYS = ["field:score", "cost_usd", "latency_ms"]


def _scores_judge() -> sf.Judge:
    return sf.Judge("provider/j", returns="scores", rubric=RUBRIC)


def _spec(reducer: Reducer, members: int = 3) -> dict[str, Any]:
    text = combine_spec_text(reducer, member_count=members, operators=flow_operators())
    return json.loads(text)


def _wrapped(reducer: Reducer) -> sf.Pipeline:
    return sf.Pipeline([sf.Fusion(members3(), synthesizer=reducer), "provider/next"])


def _url4(reducer: Reducer) -> str:
    return compile_candidate(_wrapped(reducer), operators=flow_operators()).url4


def _combine_context(url4: str) -> str:
    """The context of the combine call: the question, the panel, and any ``sources``."""

    root = build(url4)
    assert isinstance(root, Expression)
    for source in root.sources:
        if isinstance(source, Source) and source.name == "synthesis_1":
            assert isinstance(source.value, RelExpr)
            return str(source.value.context)
    raise AssertionError("no synthesis_1 source")


def test_rank_by_signal_compiles_by_signal_and_top_k() -> None:
    rank = sf.Rank(2, by_signal=sf.signal("field:score"))
    spec = _spec(rank)

    assert spec["reducer"] == "rank"
    assert (spec["extract"], spec["normalize"], spec["weights"]) == (None, None, None)
    assert spec["reduce"] == {"args": {"key": "field:score", "order": "max"}, "op": "by_signal@1"}
    assert spec["select"] == {"args": {"k": 2, "order": "max"}, "op": "top_k@1"}

    lowest = _spec(sf.Rank(2, by_signal=sf.signal("field:score"), order="min"))
    assert lowest["reduce"]["args"] == {"key": "field:score", "order": "min"}
    assert lowest["select"]["args"] == {"k": 2, "order": "min"}


def test_the_max_default_keeps_the_old_bytes_of_rank_by_field_and_by_judge() -> None:
    old_by_field = (
        '{"extract":{"args":{"path":"score"},"op":"json_field@1"},"members":'
        '["member_1","member_2","member_3"],"normalize":{"args":{},"op":"numeric@1"},'
        '"reduce":{"args":{"source":"values"},"op":"scores@1"},"reducer":"rank",'
        '"schema":"screamingface.combine-spec.v1","select":{"args":{"k":2},"op":"top_k@1"},'
        '"weights":null}'
    )
    explicit = sf.Rank(2, by_field="score", order="max")
    plain = sf.Rank(2, by_field="score")

    for rank in (plain, explicit):
        assert combine_spec_text(rank, member_count=3, operators=flow_operators()) == old_by_field
    assert explicit == plain
    judged = _spec(sf.Rank(2, by=_scores_judge()))
    assert judged["select"] == {"args": {"k": 2}, "op": "top_k@1"}


def test_the_order_option_of_by_field_and_by_judge_writes_the_order_into_top_k_only() -> None:
    by_field = _spec(sf.Rank(2, by_field="s", order="min"))
    by_judge = _spec(sf.Rank(2, by=_scores_judge(), order="min"))

    assert by_field["select"] == {"args": {"k": 2, "order": "min"}, "op": "top_k@1"}
    assert by_field["reduce"] == {"args": {"source": "values"}, "op": "scores@1"}
    assert by_judge["select"] == {"args": {"k": 2, "order": "min"}, "op": "top_k@1"}
    assert by_judge["reduce"] == {"args": {"source": "judge"}, "op": "scores@1"}
    assert sf.Rank(2, by_field="s", order="min") != sf.Rank(2, by_field="s")


@pytest.mark.parametrize("key", ["cost_usd"])
def test_an_accounting_key_emits_sources_through_the_signal_seam(key: str) -> None:
    named = _url4(sf.Rank(2, by_signal=sf.signal(key), order="min"))

    assert "sources:" in _combine_context(named)
    # a field signal needs no accounting sources
    assert "sources:" not in _combine_context(_url4(sf.Rank(2, by_signal=sf.signal("field:score"))))
    # the block form reads the same plan
    block = _url4(sf.Reduce("top_k", k=2, by_signal=sf.signal(key), order="min"))
    assert "sources:" in _combine_context(block)


def test_rank_by_signal_validation() -> None:
    with pytest.raises(TypeError, match="Rank by_signal must be an sf.signal"):
        sf.Rank(2, by_signal="field:score")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Rank order must be 'max' or 'min'"):
        sf.Rank(2, by_signal=sf.signal("cost_usd"), order="avg")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Rank order must be 'max' or 'min'"):
        sf.Rank(2, by_field="s", order=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Rank order must be 'max' or 'min'"):
        sf.Rank(2, by=_scores_judge(), order=None)  # type: ignore[arg-type]
    # score:judge has no judge here: the message names the Rank that has one
    with pytest.raises(ValueError, match=r"Rank cannot read sf\.signal\('score:judge'\)") as hint:
        sf.Rank(2, by_signal=sf.signal("score:judge"))
    assert "sf.Rank(k, by=sf.Judge(..., returns='scores'))" in str(hint.value)
    with pytest.raises(ValueError, match="score:judge"):
        sf.Reduce("top_k", k=2, by_signal=sf.signal("score:judge"))
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sf.Rank(0, by_signal=sf.signal("cost_usd"))
    with pytest.raises(ValueError, match="k=4"):
        sf.Fusion(members3(), synthesizer=sf.Rank(4, by_signal=sf.signal("cost_usd")))


def test_rank_by_signal_fields_repr_and_equality() -> None:
    signal = sf.signal("field:score")
    by_signal = sf.Rank(2, by_signal=signal)
    lowest = sf.Rank(2, by_signal=signal, order="min")

    assert (by_signal.by_signal, by_signal.order, by_signal.by, by_signal.by_field) == (
        signal,
        "max",
        None,
        None,
    )
    assert repr(by_signal) == "Rank(k=2, by_signal=signal('field:score'))"
    assert repr(lowest) == "Rank(k=2, by_signal=signal('field:score'), order='min')"
    assert by_signal._python() == "sf.Rank(k=2, by_signal=sf.signal('field:score'))"
    assert lowest._python() == "sf.Rank(k=2, by_signal=sf.signal('field:score'), order='min')"
    assert repr(sf.Rank(2, by_field="s", order="min")) == "Rank(k=2, by_field='s', order='min')"
    for rank in (by_signal, lowest, sf.Rank(2, by=_scores_judge(), order="min")):
        assert eval(rank._python(), {"sf": sf}) == rank  # noqa: S307
    assert by_signal != lowest
    assert by_signal == sf.Rank(2, by_signal=sf.signal("field:score"), order="max")
    assert by_signal != sf.Rank(2, by_signal=sf.signal("cost_usd"))
    assert by_signal != sf.Rank(2, by_field="score")
    assert by_signal != sf.Rank(3, by_signal=signal)


@pytest.mark.parametrize("order", ["min"])
def test_reduce_top_k_block_equals_sf_rank(order: str) -> None:
    pairs: list[tuple[Reducer, Reducer]] = [
        (
            sf.Reduce("top_k", k=2, by=_scores_judge(), order=order),
            sf.Rank(2, by=_scores_judge(), order=order),  # type: ignore[arg-type]
        ),
        (
            sf.Reduce("top_k", k=2, by_field="score", order=order),
            sf.Rank(2, by_field="score", order=order),  # type: ignore[arg-type]
        ),
        (
            sf.Reduce("top_k", k=2, by_field="a.b[0]", order=order),
            sf.Rank(2, by_field="a.b[0]", order=order),  # type: ignore[arg-type]
        ),
    ]
    for key in _KEYS:
        pairs.append(
            (
                sf.Reduce("top_k", k=2, by_signal=sf.signal(key), order=order),
                sf.Rank(2, by_signal=sf.signal(key), order=order),  # type: ignore[arg-type]
            )
        )

    for block, named in pairs:
        assert _url4(block) == _url4(named)


def test_reduce_top_k_block_canonical_form_equality_and_hash() -> None:
    plain = sf.Reduce("top_k", k=2, by_field="score")
    explicit = sf.Reduce("top_k", k=2, by_field="score", order="max")
    lowest = sf.Reduce("top_k", k=2, by_field="score", order="min")

    # the default order is not stored, so the two spellings are one block
    assert plain == explicit
    assert hash(plain) == hash(explicit)
    assert dict(explicit.options) == {"k": 2, "by_field": "score"}
    assert dict(lowest.options) == {"k": 2, "by_field": "score", "order": "min"}
    assert plain != lowest
    for block in (
        plain,
        lowest,
        sf.Reduce("top_k", k=3, by=_scores_judge()),
        sf.Reduce("top_k", k=2, by_signal=sf.signal("cost_usd"), order="min"),
    ):
        twin = eval(block._python(), {"sf": sf})  # noqa: S307
        assert twin == block
        assert hash(twin) == hash(block)
    assert len({plain, explicit, lowest}) == 2
    with pytest.raises(TypeError, match="option 'by' must be an sf.Judge"):
        sf.Reduce("top_k", k=2, by="provider/j")
    with pytest.raises(ValueError, match="needs sf.Judge"):
        sf.Reduce("top_k", k=2, by=sf.Judge("provider/j", returns="label", rubric=RUBRIC))
    with pytest.raises(ValueError, match="option 'order' must be 'max' or 'min'"):
        sf.Reduce("top_k", k=2, by_field="s", order="up")


@pytest.mark.parametrize(
    ("op", "option", "options"),
    [("top_k", "by_field", {"k": 2}), ("pick_field", "field", {"order": "max"})],
)
def test_a_block_path_option_is_capped_at_256_characters_with_the_op_table_message(
    op: str, option: str, options: dict[str, Any]
) -> None:
    sf.Reduce(op, **{option: "a" * 256}, **options)
    with pytest.raises(ValueError, match=rf"sf\.Reduce\('{op}'\) option '{option}'") as caught:
        sf.Reduce(op, **{option: "a" * 257}, **options)
    assert "at most 256 characters" in str(caught.value)
    with pytest.raises(ValueError, match=rf"sf\.Reduce\('{op}'\) option '{option}'"):
        sf.Reduce(op, **{option: "a b"}, **options)
