"""sf.Pick(..., output=...) makes the answer one field of the winner's reply (E4b pick-output).

FEATURE: ``output="answer"`` on a field Pick or on ``by_signal=`` compiles to an ``output`` arg of
the select step (``by_field@1`` or ``best_holder@1``). The block forms ``pick_field`` and ``argmax``
take the same option. A Pick without ``output`` compiles to the same bytes as before.
STORY: as a researcher, my scorer reads ``42`` from a JSON reply, not the whole JSON text, and a
hand-edited url4 that holds a bad ``output`` is refused.
INVARIANT defended: the field name is checked before any call (``Pick output`` ValueError or
TypeError); a Pick without ``output`` keeps its compiled spec; the url4 round trip keeps ``output``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface.answer import ABSTAIN_REASONS, ANSWER_REASONS
from screamingface.reducer import Reducer

_CANNOT_REBUILD_PICK = "pick spec this SDK version cannot rebuild"


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _fusion(synthesizer: Reducer) -> sf.Fusion:
    return sf.Fusion(members3(), synthesizer=synthesizer)


def _spec(reducer: Reducer) -> dict[str, Any]:
    return json.loads(combine_spec_text(reducer, member_count=3, operators=flow_operators()))


def _spec_of(reducer: Reducer) -> dict[str, Any]:
    return dict(
        decode_combine_spec(combine_spec_text(reducer, member_count=3, operators=flow_operators()))
    )


def _recovered(url4: str) -> Reducer:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    synthesizer = namespace["candidate"].synthesizer
    assert isinstance(synthesizer, Reducer)
    return synthesizer


def test_pick_without_output_compiles_the_same_select_args() -> None:
    assert _spec(sf.Pick("confidence", order="max"))["select"] == {
        "args": {"order": "max"},
        "op": "by_field@1",
    }
    assert _spec(sf.Pick(by_signal=sf.signal("field:confidence"), order="max"))["select"] == {
        "args": {"order": "max"},
        "op": "best_holder@1",
    }
    assert _spec(sf.Pick("label", equals="yes"))["select"] == {
        "args": {"normalize": None, "order": "equals", "value": "yes"},
        "op": "by_field@1",
    }
    assert repr(sf.Pick("confidence", order="max")) == "Pick('confidence', order='max')"
    assert sf.Pick("confidence", order="max")._python() == "sf.Pick('confidence', order='max')"


def test_sdk_pick_output_compiles_the_select_arg() -> None:
    plain = _spec(sf.Pick("confidence", order="max"))
    spec = _spec(sf.Pick("confidence", order="max", output="answer"))
    assert spec["select"] == {"args": {"order": "max", "output": "answer"}, "op": "by_field@1"}
    assert (spec["extract"], spec["normalize"], spec["reduce"]) == (
        plain["extract"],
        plain["normalize"],
        plain["reduce"],
    )

    signal = _spec(sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer"))
    assert signal["select"] == {
        "args": {"order": "max", "output": "answer"},
        "op": "best_holder@1",
    }
    assert signal["reduce"] == {
        "args": {"key": "field:confidence", "order": "max"},
        "op": "by_signal@1",
    }

    equals = _spec(sf.Pick("label", equals="yes", output="answer"))
    assert equals["select"]["args"] == {
        "normalize": None,
        "order": "equals",
        "output": "answer",
        "value": "yes",
    }

    assert _url4(
        _fusion(sf.Reduce("pick_field", field="confidence", order="max", output="answer"))
    ) == (_url4(_fusion(sf.Pick("confidence", order="max", output="answer"))))
    assert _url4(
        _fusion(
            sf.Reduce(
                "argmax", by_signal=sf.signal("field:confidence"), order="max", output="answer"
            )
        )
    ) == _url4(
        _fusion(sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer"))
    )
    assert sf.Reduce("pick_field", field="c", order="max", output="answer").options == {
        "field": "c",
        "order": "max",
        "output": "answer",
    }
    assert sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), output="answer").options == {
        "by_signal": sf.signal("cost_usd"),
        "output": "answer",
    }
    assert sf.Pick("c", order="max", output="a") != sf.Pick("c", order="max")


@pytest.mark.parametrize("bad", ["2bad", "a.b", "a[0]", "", "a" * 65, "an swer"])
def test_pick_output_with_a_bad_name_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError, match="Pick output"):
        sf.Pick("confidence", order="max", output=bad)
    with pytest.raises(ValueError, match="Pick output"):
        sf.Pick(by_signal=sf.signal("field:confidence"), output=bad)


def test_pick_output_that_is_not_text_raises_type_error() -> None:
    with pytest.raises(TypeError, match="Pick output"):
        sf.Pick("confidence", order="max", output=7)  # type: ignore[arg-type]


def test_block_output_with_a_bad_name_raises_before_any_call() -> None:
    with pytest.raises(ValueError, match=r"sf\.Reduce\('pick_field'\): Pick output"):
        sf.Reduce("pick_field", field="confidence", order="max", output="a.b")
    with pytest.raises(ValueError, match=r"sf\.Reduce\('argmax'\): Pick output"):
        sf.Reduce("argmax", by_signal=sf.signal("field:confidence"), output="a.b")
    with pytest.raises(TypeError, match="option 'output' must be text"):
        sf.Reduce("pick_field", field="c", order="max", output=7)  # type: ignore[arg-type]


def test_a_pick_output_of_the_longest_name_is_kept() -> None:
    assert sf.Pick("c", order="max", output="a" * 64).output == "a" * 64


def test_pick_repr_and_python_show_the_output() -> None:
    assert (
        repr(sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer"))
        == "Pick(by_signal=sf.signal('field:confidence'), order='max', output='answer')"
    )
    assert (
        repr(sf.Pick("confidence", order="max", output="answer"))
        == "Pick('confidence', order='max', output='answer')"
    )
    assert (
        repr(sf.Pick("label", equals="yes", normalize="text", output="answer"))
        == "Pick('label', equals='yes', normalize='text', output='answer')"
    )
    assert (
        sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer")._python()
        == "sf.Pick(by_signal=sf.signal('field:confidence'), order='max', output='answer')"
    )


@pytest.mark.parametrize(
    "original",
    [
        sf.Pick("confidence", order="max", output="answer"),
        sf.Pick(by_signal=sf.signal("field:confidence"), order="min", output="answer"),
        sf.Pick("label", equals="yes", normalize="text", output="answer"),
    ],
    ids=["field-max", "signal-min", "field-equals"],
)
def test_url4_round_trip_rebuilds_pick_output(original: sf.Pick) -> None:
    url4 = _url4(_fusion(original))
    rebuilt = _recovered(url4)

    assert type(rebuilt) is sf.Pick
    assert rebuilt == original
    assert _url4(_fusion(rebuilt)) == url4


def test_url4_to_python_shows_the_output_of_each_pick() -> None:
    pairs = [
        (
            sf.Pick("confidence", order="max", output="answer"),
            "sf.Pick('confidence', order='max', output='answer')",
        ),
        (
            sf.Pick(by_signal=sf.signal("field:confidence"), order="min", output="answer"),
            "sf.Pick(by_signal=sf.signal('field:confidence'), order='min', output='answer')",
        ),
        (
            sf.Pick("label", equals="yes", normalize="text", output="answer"),
            "sf.Pick('label', equals='yes', normalize='text', output='answer')",
        ),
    ]
    for original, expected in pairs:
        assert expected in sf.Url4(_url4(_fusion(original))).to_python()


def test_block_forms_round_trip_to_the_named_pick_with_output() -> None:
    field = sf.Pick("confidence", order="max", output="answer")
    signal = sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer")

    assert (
        _recovered(
            _url4(
                _fusion(sf.Reduce("pick_field", field="confidence", order="max", output="answer"))
            )
        )
        == field
    )
    assert (
        _recovered(
            _url4(
                _fusion(
                    sf.Reduce("argmax", by_signal=sf.signal("field:confidence"), output="answer")
                )
            )
        )
        == signal
    )


def test_pick_field_block_python_round_trips() -> None:
    block = sf.Reduce("pick_field", field="c", order="max", output="answer")
    assert eval(block._python(), {"sf": sf}) == block  # noqa: S307 - our own generated code


def test_a_rebuilt_pick_refuses_an_output_that_is_not_a_field_name() -> None:
    spec = _spec_of(sf.Pick("confidence", order="max", output="answer"))
    spec["select"] = {"op": "by_field@1", "args": {"order": "max", "output": 7}}

    with pytest.raises(ValueError, match=_CANNOT_REBUILD_PICK):
        sf.Pick._from_spec(spec)


def test_answer_v1_lists_output_missing() -> None:
    assert "output_missing" in ABSTAIN_REASONS
    assert "output_missing" in ANSWER_REASONS

    snapshot = Path(__file__).parent / "data" / "schemas" / "screamingface.answer.v1.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert data["abstain_reason"] == ["cut_not_met", "no_votes", "output_missing"]
    assert data["reason"] == [
        "cut_not_met",
        "empty",
        "field_missing",
        "missing",
        "no_match",
        "no_votes",
        "not_json",
        "not_numeric",
        "output_missing",
        "too_large",
    ]


def test_changelog_entry_names_the_pick_output_operator_ids() -> None:
    # WHY: the CS#9 check in test_mean.py takes the FIRST bullet that names `sf.Pick(`, which is
    # the older Pick bullet. This finds the pick-output bullet by its abstain reason instead.
    changelog = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    unreleased = changelog.read_text(encoding="utf-8").split("## Unreleased", 1)[1]
    unreleased = unreleased.split("\n## ", 1)[0]
    entries = [b for b in unreleased.split("\n* ") if "`output_missing`" in b]
    assert len(entries) == 1
    assert "`sf.Pick(" in entries[0]
    assert "Requires an SF Engine whose catalog has" in entries[0]
    for op_id in ("by_field@1", "best_holder@1"):
        assert f"`{op_id}`" in entries[0]
