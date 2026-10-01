"""The combine endpoint (FW-4..FW-11, FW-16, FW-17, EV-3; OME-1289 E4a, unit 1).

FEATURE: run a reducer spec over member outputs with pure functions, never a model.
Every test uses the fake operators of ``combine_support``; no built-in operator is involved.
"""

from __future__ import annotations

import json
import socket
from decimal import Decimal
from typing import Any

import httpx
import pytest
from combine_support import (
    FAKE_REGISTRY,
    context_text,
    request,
    run,
    spec_text,
    vote_spec,
)
from pydantic import ValidationError

from screamingface_engine.combine.endpoint import (
    COMBINE_ROUTE,
    CombineEndpoint,
    install_combine_runtime,
)
from screamingface_engine.combine.evidence import CombineEvidence, MemberReadingRecord
from screamingface_engine.combine.ports import (
    CombineInput,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    TallyRow,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from url4 import RelExpr, Text, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.peer.server import Url4Node

_MIB = 1024 * 1024


def _failure(intent: str, context: str, params: dict[str, str] | None = None) -> ResolutionError:
    """Run the endpoint and return the ResolutionError it raises (no call may be recorded)."""
    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as caught:
            CombineEndpoint(FAKE_REGISTRY)(request(intent, context, params))
    assert calls == []
    return caught.value


def _evidence(calls: list[OperationCall]) -> CombineEvidence:
    assert len(calls) == 1
    evidence = calls[0].combine
    assert evidence is not None
    return evidence


def _node() -> Url4Node:
    node = Url4Node("t", outbound=StaticIOLayer())
    install_combine_runtime(node, FAKE_REGISTRY)
    return node


async def _evaluate(node: Url4Node, intent: str, context: str) -> str:
    expression = expr(
        src(text(context), name="ctx", weight=0.0),
        RelExpr(
            path=COMBINE_ROUTE,
            context="$ctx",
            intent=Text(intent),
            params=(("binding", "synthesis_1"),),
        ),
        intent=Text(""),
    )
    return (await node.evaluate(render(expression))).text


# --- FW-4 -----------------------------------------------------------------------------------


def test_endpoint_returns_first_holder_text_byte_for_byte() -> None:
    texts = [" A\r\n é x ", "b x", " y\t"]
    output, calls = run(spec_text(vote_spec(3)), context_text(texts))
    assert output == texts[0]
    assert _evidence(calls).chosen == ["member_1"]


# --- EV-3 / FW-H1 ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_combine_call_through_url4_records_one_operation_call_with_evidence() -> None:
    node = _node()
    texts = ["same x", "other y", "third x"]
    with capture_operation_calls() as calls:
        result = await _evaluate(node, spec_text(vote_spec(3)), context_text(texts))
    assert result == texts[0]
    assert len(calls) == 1
    call = calls[0]
    assert call.path == COMBINE_ROUTE
    assert call.params == (("binding", "synthesis_1"),)
    assert call.output == texts[0]
    assert call.finish_reason == "stop"
    assert call.accounting is None
    assert call.combine is not None and call.combine.kind == "answer"


# --- U1-7 -----------------------------------------------------------------------------------


def test_vote_evidence_has_every_pinned_field() -> None:
    _, calls = run(spec_text(vote_spec(3)), context_text(["x", "  ", "y X"]))
    assert _evidence(calls).model_dump(by_alias=True) == {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["fake_last_word@1", "fake_lower@1", "fake_count@1", "fake_first@1"],
        "members": [
            {"member": "member_1", "raw": "x", "value": "x", "status": "voted",
             "weight": None, "score": None},
            {"member": "member_2", "raw": None, "value": None, "status": "empty",
             "weight": None, "score": None},
            {"member": "member_3", "raw": "X", "value": "x", "status": "voted",
             "weight": None, "score": None},
        ],
        "tally": [{"value": "x", "score": 2.0, "holders": ["member_1", "member_3"]}],
        "judge": None,
        "fields": None,
        "chosen": ["member_1"],
        "built": False,
        "agreement": 1.0,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "finish_reason": "stop",
    }  # fmt: skip


def test_evidence_keys_are_in_the_pinned_order() -> None:
    _, calls = run(spec_text(vote_spec(2)), context_text(["a", "b"]))
    assert list(json.loads(_evidence(calls).model_dump_json(by_alias=True))) == [
        "schema", "kind", "reducer", "operators", "members", "tally", "judge", "fields",
        "chosen", "built", "agreement", "tie", "median", "presentation_order",
        "separator_collision", "finish_reason",
    ]  # fmt: skip


def test_evidence_carries_float_weights_and_a_hand_computed_agreement() -> None:
    weights = {"member_1": 2, "member_2": 1.5, "member_3": 1}
    _, calls = run(spec_text(vote_spec(3, weights=weights)), context_text(["a", "b", "b"]))
    evidence = _evidence(calls)
    assert [row.weight for row in evidence.members] == [2.0, 1.5, 1.0]
    assert evidence.agreement == pytest.approx(2 / 3)
    assert evidence.tally is not None
    assert [(row.value, row.score) for row in evidence.tally] == [("b", 2.0), ("a", 1.0)]
    assert evidence.chosen == ["member_2"]


def _unsorted_tally(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    return Reduction(
        tally=(
            TallyRow("a", Decimal(1), ("member_1",)),
            TallyRow("b", Decimal(2), ("member_3", "member_2")),
        ),
        scores={"member_1": Decimal(1), "member_2": Decimal(2)},
    )


def test_evidence_orders_tally_rows_and_holders_by_score_then_author_position() -> None:
    registry = OperatorRegistry(
        (
            *FAKE_REGISTRY,
            OperatorDescriptor("fake_unsorted", 1, "reduce", "Unsorted rows.", _unsorted_tally),
        )
    )
    spec = vote_spec(3, reduce={"op": "fake_unsorted@1", "args": {}})
    with capture_operation_calls() as calls:
        CombineEndpoint(registry)(request(spec_text(spec), context_text(["a", "b", "b"])))
    evidence = _evidence(calls)
    assert evidence.tally is not None
    assert [(row.value, row.holders) for row in evidence.tally] == [
        ("b", ["member_2", "member_3"]),
        ("a", ["member_1"]),
    ]
    assert [row.score for row in evidence.members] == [1.0, 2.0, None]


def test_evidence_rejects_a_chosen_member_outside_the_members() -> None:
    _, calls = run(spec_text(vote_spec(2)), context_text(["a", "b"]))
    data = _evidence(calls).model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "chosen": ["member_9"]})
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "chosen": ["member_1", "member_1"]})
    row = MemberReadingRecord.model_validate(data["members"][0]).model_dump()
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "members": [row, row]})


# --- FW-5 -----------------------------------------------------------------------------------


def test_endpoint_raises_combine_no_votes_when_no_member_votes() -> None:
    error = _failure(spec_text(vote_spec(3)), context_text(["", "  ", "\n"]))
    assert error.code == "combine_no_votes"
    assert error.permanent is True


# --- FW-6 -----------------------------------------------------------------------------------


def test_endpoint_raises_combine_operator_unknown_for_unregistered_id() -> None:
    spec = vote_spec(2, extract={"op": "fake_last_word@9", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_operator_unknown"
    assert error.permanent is True
    assert "fake_last_word@9" in str(error)


def test_endpoint_rejects_an_operator_at_the_wrong_stage() -> None:
    spec = vote_spec(2, select={"op": "fake_count@1", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_spec_invalid"
    assert "fake_count@1" in str(error)


# --- U1-10 ----------------------------------------------------------------------------------


def test_operator_args_are_checked_before_the_context_is_read() -> None:
    spec = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": 1}})
    error = _failure(spec_text(spec), "this context is not json")
    assert error.code == "combine_spec_invalid"
    assert "fake_args@1 args are invalid" in str(error)
    assert "context" not in str(error)


# --- FW-8 -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the combine endpoint must not touch the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    texts = ["a x", "b x", "c y"]
    result = await _evaluate(_node(), spec_text(vote_spec(3)), context_text(texts))
    assert result == texts[0]


# --- FW-9 -----------------------------------------------------------------------------------


def _oversize_context() -> tuple[str, str]:
    return spec_text(vote_spec(3)), "x" * (64 * _MIB + 1)


def _too_many_members() -> tuple[str, str]:
    return spec_text(vote_spec(257)), "not json"


def _oversize_intent() -> tuple[str, str]:
    return "x" * (64 * 1024 + 1), context_text(["a"])


@pytest.mark.parametrize(
    "make",
    [_oversize_context, _too_many_members, _oversize_intent],
    ids=["context-64-mib-plus-1", "257-members", "intent-64-kib-plus-1"],
)
def test_oversize_context_raises_before_parsing_outputs(make: Any) -> None:
    intent, context = make()
    error = _failure(intent, context)
    assert error.code == "combine_input_too_large"
    assert error.permanent is True


# --- FW-10 ----------------------------------------------------------------------------------


def test_oversize_member_output_gets_too_large_status() -> None:
    texts = ["a x", "w " * _MIB, "c x"]
    _, calls = run(spec_text(vote_spec(3)), context_text(texts))
    evidence = _evidence(calls)
    skipped = evidence.members[1]
    assert (skipped.status, skipped.raw, skipped.value) == ("too_large", None, None)
    assert [row.status for row in evidence.members] == ["voted", "too_large", "voted"]
    assert evidence.agreement == 1.0


# --- U1-14 ----------------------------------------------------------------------------------


def test_built_output_is_returned_and_marked_built() -> None:
    spec = vote_spec(2, select={"op": "fake_constant@1", "args": {}})
    output, calls = run(spec_text(spec), context_text(["a", "b"]))
    evidence = _evidence(calls)
    assert output == "BUILT"
    assert evidence.built is True
    assert evidence.chosen == []


def test_built_output_over_8_mib_raises_input_too_large() -> None:
    spec = vote_spec(2, select={"op": "fake_huge@1", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_input_too_large"


# --- U1-15 ----------------------------------------------------------------------------------


def test_an_invalid_selection_from_a_plugin_is_a_runtime_error() -> None:
    spec = vote_spec(2, select={"op": "fake_bad@1", "args": {}})
    with capture_operation_calls() as calls:
        with pytest.raises(RuntimeError, match=r"fake_bad@1") as caught:
            CombineEndpoint(FAKE_REGISTRY)(request(spec_text(spec), context_text(["a", "b"])))
    assert not isinstance(caught.value, ResolutionError)
    assert calls == []


# --- FW-11 ----------------------------------------------------------------------------------


def test_install_combine_runtime_is_idempotent() -> None:
    node = Url4Node("t")
    install_combine_runtime(node, FAKE_REGISTRY)
    install_combine_runtime(node, FAKE_REGISTRY)
    assert node.processor_routes().count(COMBINE_ROUTE) == 1


def test_the_endpoint_exposes_its_registry() -> None:
    assert CombineEndpoint(FAKE_REGISTRY).registry is FAKE_REGISTRY


# --- FW-16 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [{}, {"binding": "synthesis_1", "temperature": "0"}, {"binding": "model_1"}],
    ids=["no-params", "extra-param", "wrong-binding"],
)
def test_endpoint_rejects_params_other_than_binding(params: dict[str, str]) -> None:
    error = _failure(spec_text(vote_spec(2)), context_text(["a", "b"]), params)
    assert error.code == "combine_spec_invalid"
    assert error.permanent is True


# --- FW-17 ----------------------------------------------------------------------------------

_LOGGER = "screamingface_engine.combine.endpoint"


def _log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _LOGGER and record.levelname == "INFO"
    ]


def test_combine_log_line_has_the_documented_fields(caplog: pytest.LogCaptureFixture) -> None:
    intent = spec_text(vote_spec(3))
    with caplog.at_level("INFO", logger=_LOGGER):
        run(intent, context_text(["x", "  ", "x"]))
        _failure(intent, context_text(["", "", ""]))
        _failure(intent, context_text(["a", "b", "c"]), {})
    assert _log_lines(caplog) == [
        "combine binding=synthesis_1 reducer=vote voters=2/3 agreement=1.0 tie=false outcome=ok",
        "combine binding=synthesis_1 reducer=vote voters=0/3 agreement=- tie=- "
        "outcome=combine_no_votes",
        "combine binding=- reducer=- voters=-/- agreement=- tie=- outcome=combine_spec_invalid",
    ]


# --- U1-19 ----------------------------------------------------------------------------------


def test_presentation_order_is_author_when_a_judge_signal_is_present() -> None:
    context = context_text(["a x", "b y"], {"judge": "member_1"})
    _, calls = run(spec_text(vote_spec(2)), context)
    assert _evidence(calls).presentation_order == "author"


# --- U1-20 ----------------------------------------------------------------------------------

_SENTINEL = "SENTINEL-TEXT-42"


def _sentinel_cases() -> dict[str, tuple[str, str, dict[str, str] | None]]:
    texts = [f"{_SENTINEL} x", f"{_SENTINEL} y"]
    context = context_text(texts)
    unknown = vote_spec(2, extract={"op": "fake_last_word@9", "args": {}})
    bad_args = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": 1}})
    huge = vote_spec(2, select={"op": "fake_huge@1", "args": {}})
    return {
        "no-votes": (
            spec_text(vote_spec(1)),
            context_text([_SENTINEL + "x" * _MIB]),
            None,
        ),
        "operator-unknown": (spec_text(unknown), context, None),
        "spec-invalid": (spec_text(vote_spec(2, surprise=1)), context, None),
        "bad-args": (spec_text(bad_args), context, None),
        "context-mismatch": (spec_text(vote_spec(3)), context, None),
        "bad-params": (spec_text(vote_spec(2)), context, {}),
        "output-too-large": (spec_text(huge), context, None),
        "context-too-large": (spec_text(vote_spec(2)), _SENTINEL + "x" * (64 * _MIB), None),
    }


@pytest.mark.parametrize("case", list(_sentinel_cases()))
def test_failure_messages_never_echo_member_text(case: str) -> None:
    intent, context, params = _sentinel_cases()[case]
    assert _SENTINEL not in str(_failure(intent, context, params))


# --- U1-21 ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spec_strings_may_escape_dollar_as_u0024() -> None:
    spec = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": "$input"}})
    intent = spec_text(spec).replace("$", "\\u0024")
    assert "$" not in intent
    with capture_operation_calls() as calls:
        result = await _evaluate(_node(), intent, context_text(["first", "second"]))
    assert result == "first"
    evidence = _evidence(calls)
    assert evidence.tally is not None
    assert evidence.tally[0].value == "$input"
    assert [row.raw for row in evidence.members] == ["$input", "$input"]
