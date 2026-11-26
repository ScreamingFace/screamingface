"""The provenance channel of a capture scope (contracts C4, C8; Unit 5.2).

FEATURE: Router Recipe extension. `capture_operation_calls` opens one channel beside its recorder:
attempt facts and call outcomes reach every active scope, as operation calls do, while a Router
step document lives in the innermost scope only and is written at most once per step and binding.

INVARIANT: no projection reads the channel; the recorder's calls are unchanged by it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from enum import StrEnum

import pytest
from router_support import fact

from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.operation_provenance import (
    CallOutcome,
    ProvenanceConflict,
    call_outcome,
    canonical_document,
    claim_step,
    current_attempt_facts,
    latest_attempt_fact,
    outcome_of,
    provenance_open,
    record_attempt_fact,
    record_call_outcome,
    record_step,
    recorded_step,
)
from screamingface_engine.world import branch
from screamingface_engine.world.router_keywords import KEYWORDS_WINDOW
from screamingface_engine.world.router_provenance import url4_row

# --- step documents -------------------------------------------------------------------------------


def test_a_step_document_is_written_once_even_when_identical() -> None:
    with capture_operation_calls():
        record_step("admit", "router_1", {"input": "q"})
        with pytest.raises(ProvenanceConflict):
            record_step("admit", "router_1", {"input": "q"})
        record_step("decide", "router_1", {"input": "q"})
        record_step("admit", "router_2", {"input": "q"})

        assert recorded_step("admit", "router_1") == '{"input":"q"}'


def test_a_step_document_needs_a_capture_scope() -> None:
    assert not provenance_open()
    with pytest.raises(ProvenanceConflict):
        record_step("admit", "router_1", {})
    assert recorded_step("admit", "router_1") is None


@pytest.mark.parametrize("isolated", [True, False], ids=["isolated", "nested"])
def test_a_step_document_lives_in_its_own_scope_only(isolated: bool) -> None:
    with capture_operation_calls():
        record_step("admit", "router_1", {"a": 1})
        with capture_operation_calls(isolated=isolated):
            assert recorded_step("admit", "router_1") is None
            record_step("admit", "router_1", {"a": 2})
        assert recorded_step("admit", "router_1") == '{"a":1}'
    assert recorded_step("admit", "router_1") is None


def test_a_router_step_is_claimed_once_per_binding_and_scope() -> None:
    # INVARIANT: every Router step runs at most once per binding and scope; a claim is not a
    # step document, so ADMIT claims first and records its result afterwards.
    with capture_operation_calls():
        claim_step("classify", "router_1")
        with pytest.raises(ProvenanceConflict):
            claim_step("classify", "router_1")
        claim_step("join", "router_1")
        claim_step("classify", "router_2")
        claim_step("admit", "router_1")
        assert recorded_step("admit", "router_1") is None
        record_step("admit", "router_1", {})
        with capture_operation_calls():
            claim_step("join", "router_1")
        with pytest.raises(ProvenanceConflict):
            claim_step("join", "router_1")


def test_outside_every_scope_a_claim_is_kept_nowhere() -> None:
    claim_step("join", "router_1")
    claim_step("join", "router_1")
    with capture_operation_calls():
        claim_step("join", "router_1")


@pytest.mark.parametrize(
    ("left", "right"),
    [(1, 1.0), (1, True), (0, False), ({"a": 1}, {"a": "1"}), ([1, 2], [2, 1])],
    ids=["int-float", "int-bool", "zero-false", "number-string", "order"],
)
def test_canonical_documents_differ_whenever_their_json_types_or_values_do(
    left: object, right: object
) -> None:
    assert canonical_document(left) != canonical_document(right)


def test_a_canonical_document_ignores_key_order_and_spacing_only() -> None:
    assert canonical_document({"b": [1, "é"], "a": None}) == '{"a":null,"b":[1,"é"]}'
    with pytest.raises(ValueError):
        canonical_document(float("nan"))


# --- attempt facts and call outcomes --------------------------------------------------------------


def test_facts_and_outcomes_reach_every_enclosing_scope_unless_isolated() -> None:
    outcome = CallOutcome("model_1", "/acme/m", "answered", "hi")
    with capture_operation_calls():
        with capture_operation_calls():
            record_attempt_fact(fact("model_1"))
            record_call_outcome(outcome)
        assert call_outcome("model_1") == outcome
        assert latest_attempt_fact("model_1") == fact("model_1")
        with capture_operation_calls(isolated=True):
            record_call_outcome(CallOutcome("model_2", "/acme/m", "answered", "x"))
            assert call_outcome("model_1") is None
            assert current_attempt_facts() == ()
        assert call_outcome("model_2") is None


def test_outside_every_scope_nothing_is_kept() -> None:
    record_attempt_fact(fact("model_1"))
    record_call_outcome(CallOutcome("model_1", "/acme/m", "answered", "hi"))

    assert latest_attempt_fact("model_1") is None
    assert call_outcome("model_1") is None
    assert current_attempt_facts() is None


def test_a_second_outcome_for_a_binding_makes_it_ambiguous_and_never_replaces_the_first() -> None:
    # INVARIANT: single assignment; one logical call per Router binding and scope.
    first = CallOutcome("model_1", "/acme/m", "failed", code="x")
    with capture_operation_calls():
        with capture_operation_calls():
            record_call_outcome(first)
            record_call_outcome(CallOutcome("model_2", "/acme/m", "failed"))
            assert call_outcome("model_1") == first
        record_call_outcome(CallOutcome("model_1", "/acme/m", "answered", "hi"))

        with pytest.raises(ProvenanceConflict):
            call_outcome("model_1")
        assert call_outcome("model_2") == CallOutcome("model_2", "/acme/m", "failed")


# --- the endpoint boundary ------------------------------------------------------------------------


class _Code(StrEnum):
    REFUSED = "endpoint_not_found"


class _Failure(Exception):
    def __init__(self, code: object, permanent: object) -> None:
        super().__init__("a message nothing keeps")
        self.code = code
        self.permanent = permanent


async def _reply(text: str) -> str:
    return text


async def _raise(failure: BaseException) -> str:
    raise failure


def _bounded(binding: object, answer: Awaitable[str]) -> tuple[object, CallOutcome | None]:
    async def scenario() -> tuple[object, CallOutcome | None]:
        with capture_operation_calls():
            try:
                value: object = await outcome_of(binding, "/acme/m", answer)
            except (Exception, asyncio.CancelledError) as exc:
                value = exc
            return value, call_outcome("model_1")

    return asyncio.run(scenario())


def test_an_answer_is_recorded_with_its_reply() -> None:
    value, outcome = _bounded("model_1", _reply("hi"))

    assert value == "hi"
    assert outcome == CallOutcome("model_1", "/acme/m", "answered", "hi")


@pytest.mark.parametrize(
    ("failure", "code", "permanent"),
    [
        (_Failure("invalid_params", True), "invalid_params", True),
        (_Failure(_Code.REFUSED, False), "endpoint_not_found", False),
        (_Failure("", "yes"), None, None),
        (_Failure(503, None), None, None),
        (ValueError("plain"), None, None),
    ],
    ids=["code-and-permanent", "str-enum-code", "empty-code-non-bool", "non-str-code", "plain"],
)
def test_a_failure_is_recorded_as_url4_writes_its_error_row(
    failure: Exception, code: str | None, permanent: bool | None
) -> None:
    # INVARIANT: exactly what `_error_payload` keeps: a non-empty string code, a boolean
    # permanence; the message is never kept.
    value, outcome = _bounded("model_1", _raise(failure))

    assert value is failure
    assert outcome == CallOutcome("model_1", "/acme/m", "failed", "", code, permanent)
    assert outcome is not None and type(outcome.code) is not _Code


def test_a_cancelled_call_records_its_cancellation_and_propagates() -> None:
    value, outcome = _bounded("model_1", _raise(asyncio.CancelledError()))

    assert isinstance(value, asyncio.CancelledError)
    assert outcome == CallOutcome("model_1", "/acme/m", "cancelled")


@pytest.mark.parametrize("binding", [None, 1], ids=["unbound", "not-a-string"])
def test_an_unbound_call_is_awaited_unchanged(binding: object) -> None:
    value, outcome = _bounded(binding, _reply("hi"))

    assert (value, outcome) == ("hi", None)


# --- what a Router step recomputes ----------------------------------------------------------------


def test_the_keywords_window_is_e4c_keywords_window() -> None:
    assert KEYWORDS_WINDOW == branch.KEYWORDS_WINDOW


@pytest.mark.parametrize(
    ("reply", "row"),
    [
        ('{"b": 1,"a":[1.50]}', '{"b": 1, "a": [1.5]}'),
        ("[NaN]", "[NaN]"),
        ("{not json", "{not json"),
        ("plain", "plain"),
        ('"quoted"', '"quoted"'),
    ],
    ids=["object", "non-finite", "brace-prose", "prose", "json-string"],
)
def test_a_reply_becomes_the_row_url4_carries(reply: str, row: str) -> None:
    assert url4_row(reply) == row
