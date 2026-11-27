"""Shared steps of the Router JOIN tests: a Case's recorded ADMIT result, draft and calls."""

from __future__ import annotations

import json
from typing import Any

from router_support import (
    ROUTER,
    Record,
    answered,
    case,
    classified,
    scores,
    step,
    text,
)
from routing_support import MODELS

from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import (
    OperationCall,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.operation_provenance import Step
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.router_decide import decide
from screamingface_engine.world.router_join import join
from screamingface_engine.world.router_steps import NOT_RUN, ROUTER_JOIN_ROUTE, StepCall
from url4.core.errors import ResolutionError

BINDING = {"binding": ROUTER}
ANSWER = "The answer is 4."
EMPTY = {"c0": "[]", "c1": "[]", "c2": "[]"}
ATTEMPTS = {"engine_attempts": 1, "upstream_attempts": 1, "possibly_billed": True}


CODE = scores(general=0.1, code=0.8, math=0.1)
TIE = scores(general=0.5, code=0.5, math=0.0)


def draft(admit: str, evidence: str, *records: Record) -> str:
    """DECIDE's draft, in a Case where ``admit`` and (for scores) ``evidence`` were recorded."""
    call = StepCall(text({"admit": admit, "evidence": evidence}), "", BINDING)
    scored = '"source":"scoring"' in admit and evidence != NOT_RUN
    with case(*records, *(classified(evidence) if scored else ())):
        step("admit", admit)
        return decide(call)


def recorded_steps(context: str) -> list[tuple[Step, str]]:
    """The ADMIT result and draft a context carries, as its occurrence recorded them."""
    try:
        document = json.loads(context)
    except ValueError:
        return []
    if not isinstance(document, dict):
        return []
    found: list[tuple[Step, object]] = [
        ("admit", document.get("admit")),
        ("decide", document.get("decision")),
    ]
    return [(name, value) for name, value in found if isinstance(value, str)]


def join_context(admit: str, decision: str, **slots: str) -> str:
    return text({"admit": admit, "decision": decision, **slots})


def joined(
    context: str,
    *records: Record,
    params: dict[str, str] | None = None,
    intent: str = "",
    priced: tuple[str, float | None] | None = None,
    steps: list[tuple[Step, str]] | None = None,
) -> tuple[str | Exception, list[OperationCall]]:
    """JOIN in a Case holding ``records`` and ``steps`` (by default the context's own ADMIT
    result and draft): its value or exception, and the records it published."""
    with case(*records) as recorded:
        for name, document in recorded_steps(context) if steps is None else steps:
            step(name, document)
        if priced is not None:
            binding, cost = priced
            with operation_call_identity("/" + MODELS["general"], {"binding": binding}):
                record_operation_call("code", "stop", signal_accounting=SignalAccounting(cost))
        try:
            value: str | Exception = join(
                StepCall(context, intent, BINDING if params is None else params)
            )
        except (RunnerRequestError, ResolutionError) as exc:
            value = exc
    return value, [call for call in recorded if call.router is not None]


def published_record(published: list[OperationCall]) -> dict[str, Any]:
    assert len(published) == 1
    (call,) = published
    assert (call.path, call.params) == (ROUTER_JOIN_ROUTE, (("binding", ROUTER),))
    assert call.router is not None
    return call.router.document()


def assert_failed(value: object, code: str, *, permanent: bool) -> None:
    assert isinstance(value, RunnerRequestError)
    assert (value.code, value.permanent) == (code, permanent)


def code_answered(reply: str = ANSWER) -> tuple[Record, ...]:
    """The selected ``code`` candidate's call (`model_2`) answered ``reply``."""
    return answered("model_2", MODELS["code"], reply)


def candidate_entry(
    index: int, label: str, status: str = "answered", code: str | None = None
) -> Any:
    entry = {"role": "candidate", "index": index, "label": label, "model": MODELS[label]}
    return {**entry, "status": status, "code": code, **ATTEMPTS}
