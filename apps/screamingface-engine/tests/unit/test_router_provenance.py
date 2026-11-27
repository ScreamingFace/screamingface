"""A Router step accepts only what its occurrence recorded (contracts C4, C5, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. url4 hands each Router step documents and rows, so a forged or
replayed context could otherwise publish a C5 record or reach a provider. ADMIT and DECIDE record
their results once per binding in the Case's capture scope; CLASSIFY, OPEN, DECIDE and JOIN accept
an ADMIT result or a draft only when it is the recorded one, and a row only as its call's recorded
outcome.

INVARIANT: every refusal here is an Engine contract error raised before any provider call, any
opening and any publication: no classification, no Model call, no C5 record.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest
from router_support import (
    QUESTION,
    ROUTER,
    ROUTES,
    SELECTOR_MODEL,
    ClassifierPort,
    Record,
    accepted,
    answered,
    case,
    classified,
    error_row,
    fact,
    failed_call,
    fixed_definition,
    llm_definition,
    router_gateway,
    rows,
    scoped,
    scores,
    step,
    text,
)
from routing_support import MODELS

from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.operation_provenance import CallOutcome, Step
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.router_admit import RouterPorts, admit, canonical_models
from screamingface_engine.world.router_decide import decide, open_branch
from screamingface_engine.world.router_join import join
from screamingface_engine.world.router_steps import ROUTER_CLASSIFY_ROUTE, StepCall
from url4.core.errors import ResolutionError

_BINDING = {"binding": ROUTER}
_ANSWER = "The answer is 4."
_CODE = scores(general=0.1, code=0.8, math=0.1)
_GENERAL = scores(general=0.8, code=0.1, math=0.1)
_SLOTS = {"c0": "[]", "c1": rows(_ANSWER), "c2": "[]"}


def _decided(admit_doc: str, evidence: str) -> str:
    """The draft DECIDE writes for ``evidence`` (in a Case of its own)."""
    with case(*classified(evidence)):
        step("admit", admit_doc)
        return decide(StepCall(text({"admit": admit_doc, "evidence": evidence}), "", _BINDING))


_ADMIT = accepted(fixed_definition())
_DRAFT = _decided(_ADMIT, _CODE)
_CONTEXT = text({"admit": _ADMIT, "decision": _DRAFT, **_SLOTS})
_RECORDS: tuple[Record, ...] = (fact(ROUTER), *answered("model_2", MODELS["code"], _ANSWER))


def _join(
    steps: list[tuple[Step, str]],
    context: str = _CONTEXT,
    records: tuple[Record, ...] = _RECORDS,
    params: dict[str, str] = _BINDING,
) -> tuple[str | Exception, list[OperationCall]]:
    with case(*records) as recorded:
        for name, document in steps:
            step(name, document)
        try:
            value: str | Exception = join(StepCall(context, "", params))
        except (RunnerRequestError, ResolutionError) as exc:
            value = exc
    return value, [call for call in recorded if call.router is not None]


def _refused(value: object, published: list[OperationCall]) -> None:
    assert isinstance(value, ResolutionError) and value.code == "benchmark_contract_error"
    assert published == []


def test_the_recorded_occurrence_joins_and_publishes_once() -> None:
    value, published = _join([("admit", _ADMIT), ("decide", _DRAFT)])

    assert value == _ANSWER
    assert len(published) == 1


# --- a forged, omitted or replayed ADMIT result or draft ------------------------------------------


_OTHER_ADMIT = accepted(fixed_definition(), "A forged question")
_FORGED_DRAFT = _decided(_ADMIT, _GENERAL)


@pytest.mark.parametrize(
    ("steps", "context"),
    [
        pytest.param([], _CONTEXT, id="nothing-recorded"),
        pytest.param([("decide", _DRAFT)], _CONTEXT, id="admit-omitted"),
        pytest.param([("admit", _ADMIT)], _CONTEXT, id="decide-omitted"),
        pytest.param(
            [("admit", _OTHER_ADMIT), ("decide", _DRAFT)], _CONTEXT, id="admit-forged-question"
        ),
        pytest.param(
            [("admit", _ADMIT), ("decide", _FORGED_DRAFT)], _CONTEXT, id="draft-another-selection"
        ),
    ],
)
def test_join_refuses_an_admit_or_draft_its_occurrence_did_not_record(
    steps: list[tuple[Step, str]], context: str
) -> None:
    _refused(*_join(steps, context))


def test_join_refuses_a_draft_naming_another_router() -> None:
    other = _DRAFT.replace(f'"router":"{ROUTER}"', '"router":"router_2"')
    steps: list[tuple[Step, str]] = [("admit", _ADMIT), ("decide", other)]

    _refused(*_join(steps, text({"admit": _ADMIT, "decision": other, **_SLOTS})))


def test_join_refuses_an_admit_recorded_under_another_binding() -> None:
    with case(*_RECORDS) as recorded:
        step("admit", _ADMIT, router="router_2")
        step("decide", _DRAFT)
        with pytest.raises(ResolutionError) as raised:
            join(StepCall(_CONTEXT, "", _BINDING))

    assert raised.value.code == "benchmark_contract_error"
    assert [call for call in recorded if call.router is not None] == []


def test_decide_runs_once_per_binding_even_for_an_identical_replay() -> None:
    call = StepCall(text({"admit": _ADMIT, "evidence": _CODE}), "", _BINDING)
    with case(*classified(_CODE)):
        step("admit", _ADMIT)
        first = decide(call)
        with pytest.raises(ResolutionError) as raised:
            decide(call)

    assert json.loads(first)["selected"] == [1]
    assert raised.value.code == "benchmark_contract_error"


def test_a_second_admit_for_one_binding_reads_nothing() -> None:
    gateway = router_gateway()
    call = StepCall(text({"input": QUESTION}), text(json.loads(_ADMIT)["spec"]), _BINDING)

    async def scenario() -> tuple[str, list[Any]]:
        async with gateway.client() as client:
            models = canonical_models(ROUTES)
            ports = RouterPorts(client=client, models=models, classify=ClassifierPort())
            with case():
                first = await admit(ports, call, _no_files)
                reads = list(gateway.calls())
                with pytest.raises(ResolutionError) as raised:
                    await admit(ports, call, _no_files)
                assert raised.value.code == "benchmark_contract_error"
            return first, reads

    first, reads = scoped(scenario)

    assert set(json.loads(first)) == {"input", "spec"}
    assert gateway.calls() == reads  # the replay made no read and no call


async def _no_files() -> None:
    return None


@pytest.mark.parametrize("recorded", [False, True], ids=["unrecorded", "another-admit"])
def test_decide_refuses_an_admit_its_occurrence_did_not_record(recorded: bool) -> None:
    call = StepCall(text({"admit": _ADMIT, "evidence": _CODE}), "", _BINDING)
    with case(*classified(_CODE)), pytest.raises(ResolutionError) as raised:
        if recorded:
            step("admit", _OTHER_ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


@pytest.mark.parametrize("in_case", [True, False], ids=["unrecorded", "outside-a-case"])
def test_open_refuses_an_unrecorded_admit_or_draft(in_case: bool) -> None:
    selector_admit = accepted(llm_definition())
    contexts = [(selector_admit, "classify"), (_DRAFT, "c1")]
    for context, intent in contexts:
        with pytest.raises(ResolutionError) as raised:
            if in_case:
                with case():
                    open_branch(StepCall(context, intent, {}))
            else:
                open_branch(StepCall(context, intent, {}))
        assert raised.value.code == "benchmark_contract_error"


def test_open_refuses_a_draft_other_than_the_recorded_one() -> None:
    with case(), pytest.raises(ResolutionError) as raised:
        step("admit", _ADMIT)
        step("decide", _DRAFT)
        open_branch(StepCall(_FORGED_DRAFT, "c0", {}))

    assert raised.value.code == "benchmark_contract_error"


# --- evidence and rows that are not their calls' --------------------------------------------------


def test_decide_refuses_scores_other_than_the_recorded_classification() -> None:
    call = StepCall(text({"admit": _ADMIT, "evidence": _GENERAL}), "", _BINDING)
    with case(*classified(_CODE)), pytest.raises(ResolutionError) as raised:
        step("admit", _ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


def test_decide_refuses_scores_whose_classification_has_no_attempt_fact() -> None:
    (outcome, _fact) = classified(_CODE)
    call = StepCall(text({"admit": _ADMIT, "evidence": _CODE}), "", _BINDING)
    with case(outcome), pytest.raises(ResolutionError) as raised:
        step("admit", _ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


_ENDED = CallOutcome(ROUTER, ROUTER_CLASSIFY_ROUTE, "failed", code="deadline_exceeded")


@pytest.mark.parametrize(
    ("evidence", "records"),
    [
        pytest.param(_CODE, (_ENDED,), id="a-control-plane-ending"),
        pytest.param("", (_ENDED,), id="an-empty-row-for-a-control-plane-ending"),
        pytest.param(
            _CODE, (CallOutcome(ROUTER, ROUTER_CLASSIFY_ROUTE, "cancelled"),), id="a-cancellation"
        ),
        pytest.param(_CODE, (*classified(_CODE), *classified(_CODE)), id="classified-twice"),
        pytest.param(
            _CODE,
            (CallOutcome(ROUTER, "/" + MODELS["code"], "answered", _CODE), fact(ROUTER)),
            id="a-chat-call-under-the-router-binding",
        ),
    ],
)
def test_decide_refuses_scores_no_single_finished_classification_wrote(
    evidence: str, records: tuple[Record, ...]
) -> None:
    # INVARIANT: a call that ended without a document gave DECIDE nothing to read, a binding
    # with two outcomes proves neither of them, and only the classify call writes scores.
    call = StepCall(text({"admit": _ADMIT, "evidence": evidence}), "", _BINDING)
    with case(*records), pytest.raises(ResolutionError) as raised:
        step("admit", _ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


_SELECTOR_ADMIT = accepted(llm_definition())


@pytest.mark.parametrize(
    "records",
    [
        pytest.param((), id="no-call"),
        pytest.param(
            (CallOutcome("selector_1", "/" + SELECTOR_MODEL, "answered", "code"),), id="no-fact"
        ),
        pytest.param(answered("selector_1", MODELS["math"], "code"), id="another-route"),
        pytest.param(answered("model_1", SELECTOR_MODEL, "code"), id="another-binding"),
        pytest.param(answered("selector_1", SELECTOR_MODEL, "math"), id="another-reply"),
        pytest.param(failed_call("selector_1", SELECTOR_MODEL), id="a-failure-left-an-answer"),
        pytest.param(
            (CallOutcome("selector_1", "/" + SELECTOR_MODEL, "cancelled"), fact("selector_1")),
            id="a-cancelled-call",
        ),
        pytest.param(
            (*answered("selector_1", SELECTOR_MODEL, "code"),) * 2, id="one-binding-called-twice"
        ),
    ],
)
def test_decide_refuses_a_selector_row_that_is_not_its_calls(records: tuple[Record, ...]) -> None:
    call = StepCall(text({"admit": _SELECTOR_ADMIT, "evidence": rows("code")}), "", _BINDING)
    with case(*records), pytest.raises(ResolutionError) as raised:
        step("admit", _SELECTOR_ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


def test_decide_refuses_a_failure_row_beside_an_answered_attempt() -> None:
    # INVARIANT (C8): a call whose HTTP attempt answered cannot have left a failure row.
    failed = CallOutcome("selector_1", "/" + SELECTOR_MODEL, "failed", code="aigateway_http_503")
    evidence = rows(error_row("aigateway_http_503"))
    call = StepCall(text({"admit": _SELECTOR_ADMIT, "evidence": evidence}), "", _BINDING)
    with (
        case(replace(failed, permanent=True), fact("selector_1")),
        pytest.raises(ResolutionError) as raised,
    ):
        step("admit", _SELECTOR_ADMIT)
        decide(call)

    assert raised.value.code == "benchmark_contract_error"


@pytest.mark.parametrize(
    "records",
    [
        pytest.param(answered("model_2", MODELS["math"], _ANSWER), id="another-route"),
        pytest.param(answered("model_3", MODELS["code"], _ANSWER), id="another-binding"),
        pytest.param(answered("model_2", MODELS["code"], "Another answer."), id="another-reply"),
        pytest.param(
            (CallOutcome("model_2", "/" + MODELS["code"], "cancelled"), fact("model_2")),
            id="a-cancelled-call",
        ),
        pytest.param(
            (*answered("model_2", MODELS["code"], _ANSWER),) * 2, id="one-binding-called-twice"
        ),
    ],
)
def test_join_refuses_a_branch_row_that_is_not_its_calls(records: tuple[Record, ...]) -> None:
    steps: list[tuple[Step, str]] = [("admit", _ADMIT), ("decide", _DRAFT)]

    _refused(*_join(steps, records=(fact(ROUTER), *records)))


_ERROR_CONTEXT = text(
    {"admit": _ADMIT, "decision": _DRAFT, **_SLOTS, "c1": rows(error_row("invalid_params"))}
)


def test_join_refuses_an_error_row_no_call_raised() -> None:
    # INVARIANT (C11): a failure row needs its recorded failure, so no row can forge one.
    steps: list[tuple[Step, str]] = [("admit", _ADMIT), ("decide", _DRAFT)]

    _refused(*_join(steps, _ERROR_CONTEXT, (fact(ROUTER),)))


_PATH = "/" + MODELS["code"]


@pytest.mark.parametrize(
    ("row", "records"),
    [
        pytest.param(
            error_row(None), (CallOutcome("model_2", _PATH, "cancelled"),), id="cancelled"
        ),
        pytest.param(
            error_row("aigateway_http_503"),
            (
                CallOutcome("model_2", _PATH, "failed", code="aigateway_http_503", permanent=True),
                fact("model_2"),
            ),
            id="failed-beside-an-answered-attempt",
        ),
    ],
)
def test_join_refuses_an_error_row_its_calls_record_contradicts(
    row: str, records: tuple[Record, ...]
) -> None:
    # INVARIANT (C8, C11): a cancellation leaves no row, and a failure row needs a failed call.
    steps: list[tuple[Step, str]] = [("admit", _ADMIT), ("decide", _DRAFT)]
    context = text({"admit": _ADMIT, "decision": _DRAFT, **_SLOTS, "c1": rows(row)})

    _refused(*_join(steps, context, (fact(ROUTER), *records)))


def test_join_publishes_a_local_failure_its_call_recorded_before_any_attempt() -> None:
    # WHY: a refusal before any HTTP attempt has no attempt fact, only its recorded outcome.
    steps: list[tuple[Step, str]] = [("admit", _ADMIT), ("decide", _DRAFT)]
    refused = failed_call("model_2", MODELS["code"], "invalid_params", attempted=False)

    value, published = _join(steps, _ERROR_CONTEXT, (fact(ROUTER), *refused))

    assert isinstance(value, Exception) and getattr(value, "code", None) == "invalid_params"
    (call,) = published
    assert call.router is not None
    record = call.router.document()
    assert record["failure"] == {"phase": "generate", "code": "invalid_params"}
    assert record["branches"] == []  # no attempt, so no Attempts to report


# --- scopes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("isolated", [True, False], ids=["isolated", "nested"])
def test_a_nested_scope_proves_only_what_it_recorded(isolated: bool) -> None:
    # INVARIANT: step documents live in the innermost scope, so a nested execution can neither
    # read nor reuse an enclosing occurrence's ADMIT result.
    call = StepCall(text({"admit": _ADMIT, "evidence": _CODE}), "", _BINDING)
    with case(*classified(_CODE)):
        step("admit", _ADMIT)
        with capture_operation_calls(isolated=isolated), pytest.raises(ResolutionError):
            decide(call)
        assert json.loads(decide(call))["selected"] == [1]


def test_concurrent_occurrences_keep_their_own_records() -> None:
    async def occurrence(evidence: str, label: str) -> tuple[str, str]:
        draft_context = text({"admit": _ADMIT, "evidence": evidence})
        selected = {"general": "c0", "code": "c1"}[label]
        model_binding = {"general": "model_1", "code": "model_2"}[label]
        reply = f"answer {label}"
        records = (*classified(evidence), *answered(model_binding, MODELS[label], reply))
        with case(*records) as recorded:
            step("admit", _ADMIT)
            await asyncio.sleep(0)
            draft = decide(StepCall(draft_context, "", _BINDING))
            await asyncio.sleep(0)
            slots = {"c0": "[]", "c1": "[]", "c2": "[]", selected: rows(reply)}
            value = join(
                StepCall(text({"admit": _ADMIT, "decision": draft, **slots}), "", _BINDING)
            )
        (call,) = [call for call in recorded if call.router is not None]
        assert call.router is not None
        return value, call.router.document()["selected"][0]["label"]

    async def both() -> list[tuple[str, str]]:
        return list(
            await asyncio.gather(occurrence(_CODE, "code"), occurrence(_GENERAL, "general"))
        )

    assert asyncio.run(both()) == [("answer code", "code"), ("answer general", "general")]
