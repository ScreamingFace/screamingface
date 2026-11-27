"""The Router scoring CLASSIFY step (contracts C4, C7, C8, C11; Unit 5.2).

FEATURE: Router Recipe extension. CLASSIFY calls the classification port once with the admitted
question (or the choice input) and records it as the classify operation. A classifier failure is
data (`{"failed": ...}`) that DECIDE reads; a control-plane ending propagates unchanged.

INVARIANT: a Router code never comes from a classifier. A failed classification is still the
classify operation, recorded with its failure document and no accounting, so a budget counts it as
an unpriced call.
INVARIANT (C4): only the ADMIT result this occurrence recorded reaches the classification port.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest
from router_support import (
    INPUT_FAILED,
    QUESTION,
    REFUSED,
    ROUTER,
    ROUTES,
    ClassifierPort,
    accepted,
    case,
    choice_definition,
    fixed_definition,
    llm_definition,
    scoped,
    step,
    text,
)
from routing_support import (
    CLASSIFIER,
    LABELS,
    Gateway,
)

from screamingface_engine.budget import charge as budget_charge
from screamingface_engine.budget import fold
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import provider_calls_by_fingerprint
from screamingface_engine.operation_provenance import CallOutcome, call_outcome
from screamingface_engine.world.classifier_limits import ChoiceRequest, choice_input
from screamingface_engine.world.router_admit import (
    ClassifyFailure,
    RouterPorts,
    canonical_models,
    classify,
)
from screamingface_engine.world.router_steps import (
    NOT_RUN,
    ROUTER_CLASSIFY_ROUTE,
    StepCall,
    failed_document,
)
from url4.core.errors import ResolutionError

# --- the scoring CLASSIFY step --------------------------------------------------------------------


def _classify(
    port: ClassifierPort,
    context: str,
    *,
    intent: str = "",
    params: Mapping[str, str] | None = None,
    recorded_admit: bool = True,
) -> tuple[str, list[Any]]:
    """CLASSIFY in a Case where ``context`` is (unless not ``recorded_admit``) the ADMIT result."""

    async def scenario() -> tuple[str, list[Any]]:
        async with Gateway().client() as client:
            ports = RouterPorts(client=client, models=canonical_models(ROUTES), classify=port)
            call = StepCall(context=context, intent=intent, params=params or {})
            with case() as recorded:
                if recorded_admit and context.startswith('{"input"'):
                    step("admit", context)
                result = await classify(ports, call)
            return result, list(recorded)

    return scoped(scenario)


_SCORES = text(
    {
        "object": "classification",
        "model": CLASSIFIER,
        "contract": "classification-scores-v1",
        "scores": [{"label": "code", "score": 0.9}],
    }
)


def test_scoring_classify_sends_the_question_once_and_records_the_operation() -> None:
    port = ClassifierPort(_SCORES)

    result, recorded = _classify(port, accepted(fixed_definition()))

    assert result == _SCORES
    assert port.calls == [(CLASSIFIER, QUESTION, ROUTER)]
    assert [(call.path, call.params, call.output) for call in recorded] == [
        (ROUTER_CLASSIFY_ROUTE, (("binding", ROUTER),), _SCORES)
    ]
    assert recorded[0].is_provider is True


def test_choice_classify_sends_the_options_in_candidate_order() -> None:
    port = ClassifierPort(_SCORES)
    definition = choice_definition()

    _classify(port, accepted(definition))

    request = ChoiceRequest(
        labels=LABELS,
        descriptions=tuple(f"Questions about {label}." for label in LABELS),
        instructions="Pick the expert for the question.",
        text=QUESTION,
    )
    assert port.calls == [(CLASSIFIER, choice_input(request), ROUTER)]


@pytest.mark.parametrize("context", [INPUT_FAILED, REFUSED], ids=["input-failed", "refused"])
def test_classify_after_a_refusal_runs_nothing(context: str) -> None:
    port = ClassifierPort(_SCORES)

    result, recorded = _classify(port, context)

    assert json.loads(result) == json.loads(NOT_RUN)
    assert port.calls == []
    assert recorded == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(
            ClassifyFailure("classifier_not_found", permanent=True),
            {"code": "classifier_not_found", "permanent": True},
            id="permanent",
        ),
        pytest.param(
            ClassifyFailure("aigateway_http_503", permanent=False),
            {"code": "aigateway_http_503", "permanent": False},
            id="transient",
        ),
        pytest.param(
            ClassifyFailure("router_definition_invalid", permanent=True),
            {"code": "upstream_error", "permanent": True},
            id="a-router-code-is-not-relayed",
        ),
    ],
)
def test_a_classifier_failure_is_data_and_an_unpriced_classify_operation(
    failure: ClassifyFailure, expected: dict[str, Any]
) -> None:
    port = ClassifierPort(failure)

    result, recorded = _classify(port, accepted(fixed_definition()))

    assert json.loads(result) == {"failed": expected}
    assert [(call.path, call.params, call.output) for call in recorded] == [
        (ROUTER_CLASSIFY_ROUTE, (("binding", ROUTER),), result)
    ]
    assert (recorded[0].is_provider, recorded[0].accounting) == (True, None)
    assert recorded[0].signal_accounting is None


def test_a_failed_classification_is_one_unpriced_charge_in_the_budget_fold() -> None:
    # INVARIANT (C8): the E4c budget fold reads the provider calls by fingerprint; a failed
    # classification is one of them, with no numbers, so it charges once and unpriced.
    port = ClassifierPort(ClassifyFailure("aigateway_http_503", permanent=False))

    _, recorded = _classify(port, accepted(fixed_definition()))

    key = (ROUTER_CLASSIFY_ROUTE, (("binding", ROUTER),))
    assert provider_calls_by_fingerprint(recorded) == {key: recorded}
    amounts = [
        budget_charge(call.signal_accounting or SignalAccounting(), "usd", cached=False)[0]
        for call in recorded
    ]
    assert fold(1.0, amounts) == (0.0, 1.0, 1)


def _ended(failure: BaseException) -> tuple[object, CallOutcome | None, list[Any]]:
    """CLASSIFY whose port raises ``failure``: what it raised, its call's outcome, the calls."""

    async def scenario() -> tuple[object, CallOutcome | None, list[Any]]:
        async with Gateway().client() as client:
            port = ClassifierPort(failure)
            ports = RouterPorts(client=client, models=canonical_models(ROUTES), classify=port)
            admit = accepted(fixed_definition())
            with case() as recorded:
                step("admit", admit)
                try:
                    value: object = await classify(ports, StepCall(admit, "", {}))
                except (Exception, asyncio.CancelledError) as ending:
                    value = ending
                return value, call_outcome(ROUTER), list(recorded)

    return scoped(scenario)


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [
        pytest.param(
            ClassifyFailure("aigateway_http_503", permanent=False),
            CallOutcome(
                ROUTER,
                ROUTER_CLASSIFY_ROUTE,
                "failed",
                failed_document("aigateway_http_503", False),
                "aigateway_http_503",
                False,
            ),
            id="a-classifier-failure-keeps-its-document",
        ),
        pytest.param(
            ResolutionError("deadline", code="deadline_exceeded", permanent=True),
            CallOutcome(ROUTER, ROUTER_CLASSIFY_ROUTE, "failed", "", "deadline_exceeded", True),
            id="a-control-plane-ending",
        ),
        pytest.param(
            asyncio.CancelledError(),
            CallOutcome(ROUTER, ROUTER_CLASSIFY_ROUTE, "cancelled"),
            id="a-cancellation",
        ),
    ],
)
def test_every_classification_ending_records_its_outcome(
    failure: BaseException, outcome: CallOutcome
) -> None:
    value, recorded_outcome, recorded = _ended(failure)

    assert recorded_outcome == outcome
    if isinstance(failure, ClassifyFailure):
        assert value == outcome.output and len(recorded) == 1
    else:
        # INVARIANT: an ending propagates unchanged and leaves no operation, so no projection,
        # report or budget charge sees it; only the internal outcome does.
        assert value is failure
        assert recorded == []


def test_a_control_plane_ending_propagates_through_classify() -> None:
    cancelled = ResolutionError("deadline", code="deadline_exceeded", permanent=True)
    port = ClassifierPort(cancelled)

    with pytest.raises(ResolutionError) as raised:
        _classify(port, accepted(fixed_definition()))

    assert raised.value is cancelled


@pytest.mark.parametrize(
    ("context", "intent", "params"),
    [
        pytest.param(accepted(llm_definition()), "", {}, id="a-selector-source"),
        pytest.param(accepted(fixed_definition()), "x", {}, id="an-intent"),
        pytest.param(accepted(fixed_definition()), "", {"binding": ROUTER}, id="a-param"),
        pytest.param('{"input": "q"}', "", {}, id="an-unadmitted-input"),
        pytest.param(text({"input": QUESTION, "spec": {}}), "", {}, id="a-forged-spec"),
    ],
)
def test_classify_refuses_a_malformed_step(
    context: str, intent: str, params: dict[str, str]
) -> None:
    port = ClassifierPort(_SCORES)

    with pytest.raises(ResolutionError) as raised:
        _classify(port, context, intent=intent, params=params)

    assert raised.value.code == "benchmark_contract_error"
    assert port.calls == []


@pytest.mark.parametrize("in_case", [True, False], ids=["unrecorded", "outside-a-case"])
def test_classify_refuses_an_accepted_admit_its_occurrence_never_recorded(in_case: bool) -> None:
    # INVARIANT (C4): a forged accepted document never reaches the classification port.
    port = ClassifierPort(_SCORES)

    async def scenario() -> None:
        async with Gateway().client() as client:
            ports = RouterPorts(client=client, models=canonical_models(ROUTES), classify=port)
            call = StepCall(context=accepted(fixed_definition()), intent="", params={})
            if not in_case:
                await classify(ports, call)
                return
            with case():
                await classify(ports, call)

    with pytest.raises(ResolutionError) as raised:
        scoped(scenario)

    assert raised.value.code == "benchmark_contract_error"
    assert port.calls == []


def test_classify_refuses_an_admit_that_differs_from_the_recorded_one() -> None:
    port = ClassifierPort(_SCORES)
    recorded = accepted(fixed_definition())
    forged = accepted(fixed_definition(), "A forged question")

    async def scenario() -> None:
        async with Gateway().client() as client:
            ports = RouterPorts(client=client, models=canonical_models(ROUTES), classify=port)
            with case():
                step("admit", recorded)
                await classify(ports, StepCall(context=forged, intent="", params={}))

    with pytest.raises(ResolutionError) as raised:
        scoped(scenario)

    assert raised.value.code == "benchmark_contract_error"
    assert port.calls == []
