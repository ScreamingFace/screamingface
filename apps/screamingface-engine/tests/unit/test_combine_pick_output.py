"""Pick returns one top-level field of the winner's JSON reply (OME-1289 E4b, pick-output).

FEATURE: the select operators ``by_field@1`` and ``best_holder@1`` take an optional ``output``
arg. The answer is that field of the chosen member's reply: a string as it is, any other JSON
value as canonical JSON. A winner without a usable field abstains with ``output_missing``.
STORY: as a researcher, my scorer reads ``42`` from a JSON reply and not the whole reply text, and
a winner without the field never hands the answer to the runner-up.
INVARIANT defended: only the chosen member is read (no fallback to the next member); a missing,
null, blank, non-JSON, non-object, oversized or non-canonical field abstains; an ``output`` that is
not a top-level field name is refused before any member is read; the message never echoes a value.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast, get_args

import httpx
import pytest
from combine_fields_support import pick_spec, step
from combine_flow_support import find_builtin, flow_input, load_flow_fixtures
from combine_signal_support import argmax_spec, costs, sources
from combine_support import context_text, run, spec_text
from fastapi import FastAPI

from screamingface_engine.app import create_app
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import (
    ABSTAIN_REASONS,
    AbstainReason,
    AnswerReason,
    NoVotes,
    Reduction,
    SelectOp,
    SpecInvalid,
)
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

_T1 = '{"answer": 42, "confidence": 0.9}'
_T2 = '{"answer": 40, "confidence": 0.6}'
_T3 = '{"answer": 41, "confidence": 0.3}'
_ABSTAIN = {"member_id": None, "value": None, "status": "abstain", "reason": "output_missing"}
_REPO_SCHEMA = Path(__file__).parent / "data" / "combine_contract" / "schemas"


def _run(spec: Any, texts: list[str], *, sources: Any = None, accounting: Any = None) -> Any:
    return run(
        spec_text(spec),
        context_text(list(texts), None, sources),
        registry=BUILTIN_OPERATORS,
        accounting=accounting,
    )


def _field_pick(select_args: dict[str, Any]) -> dict[str, Any]:  # by_field over "confidence"
    return pick_spec(3, step("by_field@1", **select_args))


def _signal_pick(
    select_args: dict[str, Any],
) -> dict[str, Any]:  # best_holder over field:confidence
    spec = argmax_spec(3, "field:confidence", "max")
    spec["select"] = {"op": "best_holder@1", "args": select_args}
    return spec


_BUILDS = [_field_pick, _signal_pick]


def _evidence(outcome: Any) -> dict[str, Any]:
    return outcome.evidence.model_dump(by_alias=True)


def test_pick_without_output_returns_the_original_text() -> None:
    outcome = _run(_field_pick({"order": "max"}), [_T1, _T2, _T3])

    assert outcome.output == _T1
    evidence = _evidence(outcome)
    assert evidence["built"] is False
    assert evidence["chosen"] == ["member_1"]
    assert evidence["result"] == {
        "member_id": "member_1",
        "value": "0.9",
        "status": "answered",
        "reason": None,
    }

    signal = _run(_signal_pick({"order": "max"}), [_T1, _T2, _T3])
    assert signal.output == _T1
    assert _evidence(signal)["result"]["member_id"] == "member_1"


def test_by_field_with_output_returns_the_winners_field() -> None:
    outcome = _run(_field_pick({"order": "max", "output": "answer"}), [_T1, _T2, _T3])

    assert outcome.output == "42"


def test_best_holder_with_output_returns_the_winners_field() -> None:
    outcome = _run(_signal_pick({"order": "max", "output": "answer"}), [_T1, _T2, _T3])

    assert outcome.output == "42"


@pytest.mark.parametrize(
    "winner",
    [
        '{"confidence": 0.9}',
        '{"answer": null, "confidence": 0.9}',
        '{"answer": "", "confidence": 0.9}',
        '{"answer": "   ", "confidence": 0.9}',
    ],
    ids=["missing", "null", "empty", "blank"],
)
@pytest.mark.parametrize("build", _BUILDS, ids=["by_field", "best_holder"])
def test_missing_null_or_blank_output_on_the_winner_abstains_with_output_missing(
    winner: str, build: Any
) -> None:
    outcome = _run(build({"order": "max", "output": "answer"}), [winner, _T2, _T3])

    assert outcome.output == ""
    evidence = _evidence(outcome)
    assert evidence["result"] == _ABSTAIN
    assert evidence["chosen"] == []
    assert evidence["built"] is False


@pytest.mark.parametrize("build", _BUILDS, ids=["by_field", "best_holder"])
def test_output_missing_does_not_fall_back_to_the_runner_up(build: Any) -> None:
    outcome = _run(build({"order": "max", "output": "answer"}), ['{"confidence": 0.9}', _T2, _T3])

    assert outcome.output == ""
    assert _evidence(outcome)["result"] == _ABSTAIN


@pytest.mark.parametrize(
    "winner",
    ["forty-two, 90% sure", "[42, 0.9]", '{"answer": 1e999}'],
    ids=["not_json", "not_an_object", "no_canonical_form"],
)
def test_non_json_or_oversized_winner_abstains_with_output_missing(winner: str) -> None:
    # the cheapest member is member_1, so the winner is the member whose reply is unusable
    spec = argmax_spec(3, "cost_usd", "min")
    spec["select"]["args"]["output"] = "answer"

    outcome = _run(
        spec,
        [winner, _T2, _T3],
        sources=sources(3),
        accounting=costs(0.001, 0.004, 0.002),
    )

    assert outcome.output == ""
    assert _evidence(outcome)["result"] == _ABSTAIN


@pytest.mark.parametrize(
    ("op", "reduction"),
    [
        (
            "best_holder@1",
            Reduction(
                scores=MappingProxyType({"member_1": Decimal("2"), "member_2": Decimal("1")})
            ),
        ),
        ("by_field@1", Reduction()),
    ],
    ids=["best_holder", "by_field"],
)
def test_an_oversized_winner_reply_raises_output_missing_in_the_operator(
    op: str, reduction: Reduction
) -> None:
    # WHY the operator: the core marks a member over 1 MiB too_large, so only the operator sees one
    big = '{"answer": "' + "x" * (1024 * 1024) + '"}'
    row_1 = {"member": "member_1", "raw": "0.9", "value": "0.9", "status": "voted", "weight": None}
    row_2 = {"member": "member_2", "raw": "0.6", "value": "0.6", "status": "voted", "weight": None}
    combine_input = flow_input(
        {"readings": [row_1, row_2], "outputs": {"member_1": big, "member_2": _T2}}
    )

    with pytest.raises(NoVotes) as caught:
        cast("SelectOp", find_builtin(op).run)(
            reduction, combine_input, {"order": "max", "output": "answer"}
        )
    assert caught.value.reason == "output_missing"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"forty-two"', "forty-two"),
        ('" 42 "', " 42 "),
        ('"caf\\u00e9"', "café"),
        ("42", "42"),
        ("4.5", "4.5"),
        ("0", "0"),
        ("true", "true"),
        ("false", "false"),
        ('{"b": 2, "a": 1}', '{"a":1,"b":2}'),
        ('[1, "x"]', '[1,"x"]'),
    ],
)
def test_output_string_is_unquoted_and_number_is_canonical_json(raw: str, expected: str) -> None:
    texts = ['{"answer": ' + raw + ', "confidence": 0.9}', '{"answer": "z", "confidence": 0.1}']

    outcome = _run(pick_spec(2, step("by_field@1", order="max", output="answer")), texts)

    assert outcome.output == expected


def test_equals_order_with_output_uses_the_first_holder() -> None:
    spec = pick_spec(
        3,
        step("by_field@1", order="equals", value="yes", normalize=None, output="answer"),
        normalize=None,
        path="label",
    )
    texts = [
        '{"label": "no", "answer": "A"}',
        '{"label": "yes", "answer": "B"}',
        '{"label": "yes", "answer": "C"}',
    ]

    outcome = _run(spec, texts)

    assert outcome.output == "B"
    evidence = _evidence(outcome)
    assert evidence["chosen"] == ["member_2"]
    assert evidence["tie"] is True


@pytest.mark.parametrize("build", _BUILDS, ids=["by_field", "best_holder"])
def test_tie_with_output_uses_the_first_member(build: Any) -> None:
    texts = [
        '{"answer": 1, "confidence": 0.9}',
        '{"answer": 2, "confidence": 0.9}',
        '{"answer": 3, "confidence": 0.5}',
    ]

    outcome = _run(build({"order": "max", "output": "answer"}), texts)

    assert outcome.output == "1"
    evidence = _evidence(outcome)
    assert evidence["chosen"] == ["member_1"]
    assert evidence["tie"] is True


@pytest.mark.parametrize("build", _BUILDS, ids=["by_field", "best_holder"])
def test_fenced_json_winner_gives_the_same_output(build: Any) -> None:
    fenced = 'Here is my reply.\n```json\n{"answer": 42, "confidence": 0.9}\n```'
    args = {"order": "max", "output": "answer"}

    outcome = _run(build(args), [fenced, _T2, _T3])

    assert outcome.output == "42"
    assert outcome.output == _run(build(args), [_T1, _T2, _T3]).output


_GOOD_ARGS: list[tuple[str, dict[str, Any]]] = [
    ("by_field@1", {"order": "max", "output": "answer"}),
    ("by_field@1", {"order": "min", "output": "_a1"}),
    ("by_field@1", {"order": "equals", "value": "yes", "normalize": None, "output": "answer"}),
    ("by_field@1", {"order": "max", "output": "a" * 64}),
    ("best_holder@1", {"order": "max", "output": "answer"}),
    ("best_holder@1", {"order": "min", "output": "a" * 64}),
]
_BAD_NAMES: list[Any] = ["2bad", "a.b", "a[0]", "", "a" * 65, "an swer", 7, None]


@pytest.mark.parametrize(("op", "args"), _GOOD_ARGS)
def test_output_arg_of_a_field_name_is_accepted(op: str, args: dict[str, Any]) -> None:
    find_builtin(op).check_args(args)


@pytest.mark.parametrize("op", ["by_field@1", "best_holder@1"])
@pytest.mark.parametrize("bad", _BAD_NAMES, ids=[repr(name)[:20] for name in _BAD_NAMES])
def test_output_arg_with_a_bad_name_is_spec_invalid(op: str, bad: Any) -> None:
    with pytest.raises(SpecInvalid) as caught:
        find_builtin(op).check_args({"order": "max", "output": bad})
    if bad == "2bad":
        assert "2bad" not in str(caught.value)


@pytest.mark.parametrize("op", ["by_field@1", "best_holder@1"])
def test_output_arg_with_an_extra_key_is_spec_invalid(op: str) -> None:
    with pytest.raises(SpecInvalid):
        find_builtin(op).check_args({"order": "max", "output": "answer", "x": 1})


def test_core_refuses_an_output_path_before_any_member_is_used() -> None:
    with pytest.raises(SpecInvalid):
        _run(_field_pick({"order": "max", "output": "a.b"}), [_T1, _T2, _T3])


def test_evidence_records_the_output_as_the_result_value() -> None:
    evidence = _evidence(_run(_field_pick({"order": "max", "output": "answer"}), [_T1, _T2, _T3]))

    assert evidence["kind"] == "answer"
    assert evidence["reducer"] == "pick"
    assert evidence["operators"] == ["json_field@1", "numeric@1", "values@1", "by_field@1"]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["tie"] is False
    assert evidence["built"] is True
    assert evidence["result"] == {
        "member_id": None,
        "value": "42",
        "status": "answered",
        "reason": None,
    }
    assert evidence["fields"] == [
        {
            "field": "confidence",
            "rule": "values",
            "values": {"member_1": "0.9", "member_2": "0.6", "member_3": "0.3"},
            "result": None,
        }
    ]


def test_by_field_and_best_holder_goldens_cover_output() -> None:
    fixtures = load_flow_fixtures()

    for op_id in ("by_field@1", "best_holder@1"):
        cases = fixtures[op_id]["cases"]
        assert any(
            "output" in case["args"] and case["expect"].get("output") is not None for case in cases
        )
        assert any(case["expect"] == {"abstain": "output_missing"} for case in cases)
        assert any(
            "output" in case["args"] and case["expect"] == {"error": "combine_spec_invalid"}
            for case in cases
        )


def test_answer_and_evidence_v1_list_output_missing() -> None:
    assert get_args(AbstainReason) == ("no_votes", "cut_not_met", "output_missing", "gate_not_met")
    assert ABSTAIN_REASONS == ("no_votes", "cut_not_met", "output_missing", "gate_not_met")
    assert get_args(AnswerReason)[-1] == "gate_not_met"
    assert NoVotes(reason="output_missing").reason == "output_missing"

    schema = json.loads(
        (_REPO_SCHEMA / "screamingface.combine-evidence.v1.json").read_text("utf-8")
    )
    enums = list(_enum_lists(schema))
    no_votes_lists = [items for items in enums if "no_votes" in items]
    assert len(no_votes_lists) == 2
    assert all(items[-1] == "gate_not_met" for items in no_votes_lists)


def _enum_lists(node: object) -> list[list[str]]:
    """Every list stored under an ``enum`` key, found at any depth."""
    found: list[list[str]] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "enum" and isinstance(value, list):
                found.append(value)
            found.extend(_enum_lists(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_enum_lists(item))
    return found


async def _get(app: FastAPI, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_operator_args_schemas_allow_output() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = (await _get(app, "/v1/operators")).json()["data"]
    schemas = {entry["id"]: entry["args_schema"] for entry in listed}

    assert schemas["by_field@1"] == {
        "type": "object",
        "properties": {
            "order": {"enum": ["max", "min", "equals"]},
            "value": {"type": "string"},
            "normalize": {"enum": [None, "text", "numeric"]},
            "output": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]{0,63}$"},
        },
        "required": ["order"],
        "additionalProperties": False,
    }
    assert schemas["best_holder@1"] == {
        "type": "object",
        "properties": {
            "order": {"enum": ["max", "min"]},
            "output": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]{0,63}$"},
        },
        "required": ["order"],
        "additionalProperties": False,
    }
