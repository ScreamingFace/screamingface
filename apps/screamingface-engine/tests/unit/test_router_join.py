"""Router JOIN: the single publisher of the completed C5 record (contracts C4, C5, C8, C11).

FEATURE: Router Recipe extension. JOIN reads ADMIT's result, DECIDE's draft and the iterate rows,
publishes one completed `router-decision.v1` record under ``?binding=router_N``, and only then
returns the answer, returns ``""`` for an abstention, or raises the failing operation's code.

INVARIANT: every Router outcome publishes exactly one record before JOIN returns or raises; a
malformed context publishes none. The record keeps labels, numbers, IDs and bounded codes, never
the question, the answer or an error message. Attempts come only from C8 attempt facts.
INVARIANT (C4): JOIN reads only the ADMIT result and draft this occurrence recorded, and a row
only as its call's recorded outcome; the answer is the recorded reply.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from router_join_support import ANSWER as _ANSWER
from router_join_support import ATTEMPTS as _ATTEMPTS
from router_join_support import BINDING as _BINDING
from router_join_support import CODE as _CODE
from router_join_support import EMPTY as _EMPTY
from router_join_support import TIE as _TIE
from router_join_support import assert_failed as _failed
from router_join_support import candidate_entry as _candidate
from router_join_support import code_answered as _code_answered
from router_join_support import draft as _draft
from router_join_support import join_context as _context
from router_join_support import joined as _join
from router_join_support import published_record as _record
from router_support import (
    INPUT_FAILED,
    QUESTION,
    REFUSED,
    ROUTER,
    SELECTOR_MODEL,
    Record,
    accepted,
    answered,
    error_row,
    fact,
    failed_call,
    fixed_definition,
    llm_definition,
    model,
    regex_definition,
    rows,
    text,
)
from routing_support import MODELS, PUBLIC

from screamingface_engine.operation_provenance import CallOutcome
from screamingface_engine.world.router_steps import NOT_RUN
from url4.core.errors import ResolutionError

# --- answered, default, abstained -----------------------------------------------------------------


def test_a_selected_candidate_answers_and_the_record_says_who() -> None:
    definition = fixed_definition()
    admit = accepted(definition)
    decision = _draft(admit, _CODE)
    context = _context(admit, decision, **{**_EMPTY, "c1": rows(_ANSWER)})

    value, published = _join(context, fact(ROUTER), *_code_answered())

    assert value == _ANSWER
    record = _record(published)
    draft = json.loads(decision)
    assert record == {
        **draft,
        "schema": "screamingface.router-decision.v1",
        "selected": [{"index": 1, "label": "code", "model": MODELS["code"]}],
        "classifier_call": {"binding": ROUTER, "cost": None, **_ATTEMPTS},
        "branches": [_candidate(1, "code")],
        "quorum": None,
        "synthesis": None,
        "status": "answered",
        "failure": None,
    }
    assert published[0].output == _ANSWER
    serialized = json.dumps(record)
    assert QUESTION not in serialized and _ANSWER not in serialized


def test_the_default_answers_a_tie() -> None:
    definition = fixed_definition(default=model(PUBLIC))
    admit = accepted(definition)
    context = _context(admit, _draft(admit, _TIE), **_EMPTY, d=rows(_ANSWER))

    value, published = _join(context, fact(ROUTER), *answered("model_4", PUBLIC, _ANSWER))

    assert value == _ANSWER
    record = _record(published)
    assert (record["outcome"], record["status"], record["selected"]) == ("default", "answered", [])
    assert record["classifier_call"] == {"binding": ROUTER, "cost": None, **_ATTEMPTS}
    assert record["branches"] == [
        {"role": "default", "index": None, "label": None, "model": PUBLIC, "status": "answered"}
        | {"code": None, **_ATTEMPTS}
    ]


def test_no_selection_abstains_with_an_empty_answer() -> None:
    admit = accepted(fixed_definition())
    context = _context(admit, _draft(admit, _TIE), **_EMPTY)

    value, published = _join(context, fact(ROUTER))

    assert value == ""
    record = _record(published)
    assert (record["outcome"], record["status"], record["failure"]) == (
        "no_selection",
        "abstained",
        None,
    )
    assert record["branches"] == []
    assert published[0].output == ""


@pytest.mark.parametrize(
    "records",
    [
        pytest.param(
            (CallOutcome("model_2", "/" + MODELS["code"], "answered", _ANSWER),), id="no-fact"
        ),
        pytest.param((), id="no-call"),
        pytest.param((fact("model_2"),), id="a-fact-and-no-outcome"),
    ],
)
def test_an_answer_without_its_call_and_attempt_fact_publishes_nothing(
    records: tuple[Record, ...],
) -> None:
    # INVARIANT (C8): an answer reaches a caller only through an HTTP attempt, so an answer row
    # with no recorded call or no attempt fact is lost or forged execution state.
    admit = accepted(fixed_definition())
    context = _context(admit, _draft(admit, _CODE), **{**_EMPTY, "c1": rows(_ANSWER)})

    value, published = _join(context, fact(ROUTER), *records)

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert published == []


def test_scoring_evidence_without_its_classifier_fact_publishes_nothing() -> None:
    # INVARIANT (C5): the evidence exists because the classifier answered, so its call has Attempts.
    admit = accepted(fixed_definition())
    context = _context(admit, _draft(admit, _CODE), **{**_EMPTY, "c1": rows(_ANSWER)})

    value, published = _join(context, *_code_answered())

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    # WHY the message: JOIN refuses before it assembles a record, not by the C5 codec's backstop.
    assert "evidence without its classifier's call" in str(value)
    assert published == []


# --- failures publish before they raise -----------------------------------------------------------


@pytest.mark.parametrize(
    ("admit", "phase", "code"),
    [
        (INPUT_FAILED, "input", "router_input_missing"),
        (REFUSED, "admit", "router_definition_invalid"),
    ],
)
def test_an_unadmitted_occurrence_fails_with_its_carried_code(
    admit: str, phase: str, code: str
) -> None:
    context = _context(admit, _draft(admit, NOT_RUN), **_EMPTY)

    value, published = _join(context)

    _failed(value, code, permanent=True)
    record = _record(published)
    assert (record["revision"], record["policy"], record["evidence"]) == (None, None, None)
    assert (record["status"], record["failure"]) == ("failed", {"phase": phase, "code": code})
    assert (record["classifier_call"], record["branches"]) == (None, [])
    assert QUESTION not in str(value)


def test_a_transient_admit_refusal_raises_transient() -> None:
    admit = text({"refused": {"code": "routing_preflight_unavailable", "permanent": False}})
    value, published = _join(_context(admit, _draft(admit, "[]")))

    _failed(value, "routing_preflight_unavailable", permanent=False)
    assert _record(published)["failure"] == {
        "phase": "admit",
        "code": "routing_preflight_unavailable",
    }


def test_a_classifier_failure_fails_at_classify_with_its_attempts() -> None:
    admit = accepted(fixed_definition())
    evidence = text({"failed": {"code": "aigateway_http_503", "permanent": False}})
    context = _context(admit, _draft(admit, evidence), **_EMPTY)

    value, published = _join(context, fact(ROUTER, "failed", "aigateway_http_503"))

    _failed(value, "aigateway_http_503", permanent=False)
    record = _record(published)
    assert record["failure"] == {"phase": "classify", "code": "aigateway_http_503"}
    assert record["classifier_call"] == {"binding": ROUTER, "cost": None, **_ATTEMPTS}
    assert record["branches"] == []


def test_invalid_evidence_fails_at_decide() -> None:
    admit = accepted(fixed_definition())
    context = _context(admit, _draft(admit, NOT_RUN), **_EMPTY)

    value, published = _join(context)

    _failed(value, "router_evidence_invalid", permanent=True)
    assert _record(published)["failure"] == {"phase": "decide", "code": "router_evidence_invalid"}


def test_a_failed_candidate_fails_at_generate_and_keeps_the_decision() -> None:
    admit = accepted(fixed_definition())
    row = error_row("aigateway_http_429", retryable=True)
    context = _context(admit, _draft(admit, _CODE), **{**_EMPTY, "c1": rows(row)})

    failed = failed_call("model_2", MODELS["code"], "aigateway_http_429", permanent=False)

    value, published = _join(context, fact(ROUTER), *failed)

    _failed(value, "aigateway_http_429", permanent=False)
    record = _record(published)
    assert (record["outcome"], record["status"]) == ("selected", "failed")
    assert record["failure"] == {"phase": "generate", "code": "aigateway_http_429"}
    assert record["branches"] == [_candidate(1, "code", "failed", "aigateway_http_429")]
    assert "an upstream said no" not in json.dumps(record)


def test_a_failed_default_fails_at_default() -> None:
    admit = accepted(fixed_definition(default=model(PUBLIC)))
    context = _context(admit, _draft(admit, _TIE), **_EMPTY, d=rows(error_row()))

    value, published = _join(context, fact(ROUTER), *failed_call("model_4", PUBLIC))

    _failed(value, "aigateway_http_503", permanent=True)
    assert _record(published)["failure"] == {"phase": "default", "code": "aigateway_http_503"}


# --- a Router code never comes from a call (C11) --------------------------------------------------


_SPOOF = error_row("router_unsupported")


@pytest.mark.parametrize(
    "reply",
    [_SPOOF, '{"answer":"\u00e9","n":[1,2]}', "[NaN, 1.5]", "{not json", "4"],
    ids=["error-row-shaped", "json-object", "non-finite", "brace-prose", "scalar-text"],
)
def test_an_answered_reply_is_the_answer_byte_for_byte(reply: str) -> None:
    # INVARIANT (C11): an answered call's reply is the answer, even shaped like an error row.
    # WHY: url4 re-encodes a visibly structured row (url4 spec 5.3.8); JOIN checks the row is
    # that re-encoding of the recorded reply and returns the reply itself.
    admit = accepted(fixed_definition())
    context = _context(admit, _draft(admit, _CODE), **{**_EMPTY, "c1": rows(reply)})

    value, published = _join(context, fact(ROUTER), *_code_answered(reply))

    assert value == reply
    assert _record(published)["status"] == "answered"


_ROUTER_CODE = "router_definition_invalid"


@pytest.mark.parametrize(
    "records",
    [
        failed_call("model_2", MODELS["code"], _ROUTER_CODE, fact_code="router_unsupported"),
        failed_call("model_2", MODELS["code"], _ROUTER_CODE, attempted=False),
    ],
    ids=["fact-code", "row-code"],
)
def test_a_router_code_from_a_call_is_bounded_to_upstream_error(
    records: tuple[Record, ...],
) -> None:
    admit = accepted(fixed_definition())
    row = error_row(_ROUTER_CODE)
    context = _context(admit, _draft(admit, _CODE), **{**_EMPTY, "c1": rows(row)})

    value, published = _join(context, fact(ROUTER), *records)

    _failed(value, "upstream_error", permanent=True)
    assert _record(published)["failure"] == {"phase": "generate", "code": "upstream_error"}


# --- the classifier call -------------------------------------------------------------------------


@pytest.mark.parametrize("cost", [0.002, None])
def test_an_llm_selector_call_reports_its_cost_or_null(cost: float | None) -> None:
    admit = accepted(llm_definition())
    selector = answered("selector_1", SELECTOR_MODEL, "code")
    decision = _draft(admit, rows("code"), *selector)
    context = _context(admit, decision, **{**_EMPTY, "c1": rows(_ANSWER)})

    value, published = _join(context, *selector, *_code_answered(), priced=("selector_1", cost))

    assert value == _ANSWER
    call = _record(published)["classifier_call"]
    assert call == {"binding": "selector_1", "cost": cost, **_ATTEMPTS}


def test_a_regex_classifier_makes_no_classifier_call() -> None:
    admit = accepted(regex_definition(), "Some math, please")
    keywords = text(
        {"summary": {"chars": 1, "sha256": "0" * 16}, ROUTER: {"labels": ["math"], "matched": []}}
    )
    context = _context(admit, _draft(admit, rows(keywords)), **{**_EMPTY, "c2": rows(_ANSWER)})

    value, published = _join(context, *answered("model_3", MODELS["math"], _ANSWER))

    assert value == _ANSWER
    record = _record(published)
    assert record["classifier_call"] is None
    assert record["selected"] == [{"index": 2, "label": "math", "model": MODELS["math"]}]


# --- a malformed context is a contract error and publishes nothing --------------------------------


def _selected_context(**changes: Any) -> str:
    admit = accepted(fixed_definition())
    slots = {**_EMPTY, "c1": rows(_ANSWER)}
    document = {"admit": admit, "decision": _draft(admit, _CODE), **slots}
    document.update(changes)
    return text({key: value for key, value in document.items() if value is not None})


@pytest.mark.parametrize(
    "context",
    [
        _selected_context(decision=None),
        _selected_context(admit=None),
        _selected_context(c2=None),
        _selected_context(c3="[]"),
        _selected_context(d="[]"),
        _selected_context(panel="[]"),
        _selected_context(c0=rows("stray")),
        _selected_context(c1="[]"),
        _selected_context(c1=rows(_ANSWER, _ANSWER)),
        _selected_context(c1='"not rows"'),
        _selected_context(c1="[4]"),
        _selected_context(decision="{}"),
        _selected_context(decision=_draft(accepted(fixed_definition()), _TIE)),
        _selected_context(decision=_draft(REFUSED, NOT_RUN)),
        _selected_context(admit=accepted(fixed_definition(default=model(PUBLIC)))),
        _selected_context(admit=REFUSED),
        "[]",
    ],
    ids=[
        "no-decision",
        "no-admit",
        "missing-slot",
        "out-of-range-slot",
        "default-without-default",
        "panel",
        "unopened-slot-ran",
        "opened-slot-empty",
        "opened-slot-two-rows",
        "slot-not-rows",
        "row-neither-text-nor-structure",
        "not-a-draft",
        "draft-chose-otherwise",
        "draft-of-a-refusal",
        "another-revision",
        "refused-admit-with-a-selection",
        "not-an-object",
    ],
)
def test_a_malformed_join_context_publishes_nothing(context: str) -> None:
    value, published = _join(context, fact(ROUTER), *_code_answered())

    assert isinstance(value, ResolutionError)
    assert value.code == "benchmark_contract_error"
    assert published == []


_OTHER_REFUSAL = text({"refused": {"code": "router_unsupported", "permanent": True}})


@pytest.mark.parametrize(
    ("context", "records"),
    [
        (_context(REFUSED, _draft(_OTHER_REFUSAL, NOT_RUN), **_EMPTY), ()),
        (_context(REFUSED, _draft(REFUSED, NOT_RUN), c0=rows(_ANSWER)), ()),
        (_selected_context(), (fact(ROUTER), *failed_call("model_2", MODELS["code"]))),
    ],
    ids=["carried-another-code", "unadmitted-ran-a-branch", "failed-call-left-an-answer"],
)
def test_a_join_that_disagrees_with_its_facts_publishes_nothing(
    context: str, records: tuple[Record, ...]
) -> None:
    value, published = _join(context, *records)

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert published == []


@pytest.mark.parametrize(
    ("params", "intent"),
    [({"binding": "router_2"}, ""), (_BINDING, "x"), ({}, ""), ({**_BINDING, "x": "1"}, "")],
    ids=["another-router", "an-intent", "no-binding", "an-extra-param"],
)
def test_join_takes_its_own_binding_and_no_intent(params: dict[str, str], intent: str) -> None:
    value, published = _join(_selected_context(), params=params, intent=intent)

    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert published == []
