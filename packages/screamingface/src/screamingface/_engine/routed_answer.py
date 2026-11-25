"""Answer one question through the Engine's ``/route-answer`` endpoint (OME-1823).

Stage 1 - build ``/route-answer?q=(<context>)!route-answer`` and refuse it before any request
    when a value cannot be encoded as UTF-8 or the request passes the Engine's 8 KiB limit.
Stage 2 - the shared direct GET (``_engine/direct_get.py``): one call, never re-sent, and at most
    one artifact fetch.
Stage 3 - decode the result, checking every rule of spec 3.6, or raise the error the Engine's
    answer names.

INVARIANT: retryable only where nothing ran: a connect-phase failure, an ingress `429`, and
`routing_preflight_unavailable`. WHY `503` is not, unlike ``classify``: a queue-publish `503` may
follow a run the broker stored when its acknowledgement was lost, and repeating a routed answer
can bill two models. A `429` inside a run reaches the caller as a relayed code on a `502`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import NoReturn

import httpx

from screamingface._engine.direct_get import (
    DirectCall,
    EngineGet,
    encode_call,
    finite_float,
    get_body,
    result_unavailable,
    url4_error,
)
from screamingface.classification import LabelScore
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    ExecutionError,
    PlanningError,
)
from screamingface.routing import RoutedAnswer

ROUTE_ANSWER_PATH = "/route-answer"
_INTENT = "route-answer"
_CALL = DirectCall(
    noun="routed answer",
    verb="route an answer",
    outcome_code="routed_answer_outcome_unknown",
    # WHY 60: a routed answer is two model calls in one run; the Engine caps the wait at its
    # `sync_max_wait_s`, so a stated 60 never waits longer than the server allows.
    wait_s=60,
    rerun_hint="Asking again may run and bill the classifier, and the selected model, again.",
)
_EXPECTED: Mapping[str, str] = {
    "object": "routed_answer",
    "contract": "routed-answer-v1",
    "policy": "unique-argmax-v1",
}
_CLASSIFICATION_CONTRACT = "classification-scores-v1"
_REVISION = re.compile(r"sha256:[0-9a-f]{64}")
#: The statuses of a refusal the caller can only fix by changing the request or its access.
_REFUSAL_STATUSES = frozenset({400, 404, 409, 414})
_RESULT_UNAVAILABLE = "result_unavailable"
_PREFLIGHT_UNAVAILABLE = "routing_preflight_unavailable"
#: The preflight refusals: decided on metadata alone, before any model was called.
_PREFLIGHT_REFUSED = frozenset({"routing_preflight_failed", "routing_profile_mismatch"})
#: One 404 for an unknown profile and for a branch the caller lost after the classifier ran.
_PROFILE_NOT_FOUND = "routing_profile_not_found"


def route_answer(get: EngineGet, engine_url: str, profile: str, text: str) -> RoutedAnswer:
    """The answer of the model ``profile`` selects for ``text``, with the scores behind it.

    e.g. ``route_answer(client._engine_get, url, "expert_router_v1", "Sort a list")`` gives
    ``RoutedAnswer(..., selected_label="code", answer="...")``.
    """

    # Stage 1 - a request the Engine will take.
    if not isinstance(profile, str) or not isinstance(text, str):
        raise TypeError("route_answer takes a profile ID and an input text, both str")
    path: str = encode_call(
        _CALL,
        ROUTE_ANSWER_PATH,
        _INTENT,
        {"profile": ("profile ID", profile), "input": ("input text", text)},
    )
    # Stage 2 - one call, and at most one artifact fetch.
    body: bytes = get_body(_CALL, get, engine_url, path, _raise_refusal)
    # Stage 3 - the result, checked.
    return _decode(body, profile)


def _raise_refusal(status: int, _headers: httpx.Headers, body: bytes) -> NoReturn:
    error: tuple[str, str] | None = url4_error(body)
    if error is None and status == 404:
        # WHY by the envelope: an Engine without `/route-answer` answers its framework's plain
        # 404, while an Engine that serves it answers an unknown profile with url4's envelope.
        raise EngineCapabilityError(
            "this SF Engine does not serve /route-answer",
            status=404,
            permanent=True,
            details={"path": ROUTE_ANSWER_PATH},
            hint="Use an SF Engine that serves /route-answer, or update the local Engine.",
        )
    code, message = error if error is not None else (None, f"HTTP {status}")
    if code == _RESULT_UNAVAILABLE:
        # WHY first: the Engine answers it, as `404` too, for a run that finished and whose
        # result it can no longer serve; the models ran and billed.
        raise result_unavailable(_CALL, status)
    if status in (401, 403):
        raise AuthenticationError(
            f"The SF Engine refused the caller: {message}", code=code, status=status, permanent=True
        )
    if code == _PREFLIGHT_UNAVAILABLE or status == 429:
        # INVARIANT: nothing ran. A transient metadata read stops before the classifier, and an
        # HTTP `429` comes from the ingress before any run.
        raise ExecutionError(
            f"The SF Engine did not start the routed answer: {message}",
            code=code,
            status=status,
            permanent=False,
        )
    if code in _PREFLIGHT_REFUSED:
        raise ExecutionError(
            f"The SF Engine refused the routed answer before any model ran: {message}",
            code=code,
            status=status,
            permanent=True,
        )
    if status in _REFUSAL_STATUSES:
        # INVARIANT (spec 6.1 C10): the Engine answers an unknown profile and a branch that is no
        # longer the caller's with the same 404, and the second can follow a classifier call that
        # billed. Telling them apart would leak the private target, so every one carries the hint.
        raise PlanningError(
            f"The SF Engine refused the routed answer: {message}",
            code=code,
            status=status,
            permanent=True,
            hint=_CALL.rerun_hint if code == _PROFILE_NOT_FOUND else None,
        )
    raise ExecutionError(
        f"The routed answer did not finish and may have run and been billed: {message}",
        code=code,
        status=status,
        permanent=True,
        hint=_CALL.rerun_hint,
    )


def _decode(body: bytes, profile: str) -> RoutedAnswer:
    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError):
        _malformed()
    if not isinstance(document, dict) or any(
        document.get(key) != value for key, value in _EXPECTED.items()
    ):
        _malformed()
    revision: object = document.get("revision")
    classification: object = document.get("classification")
    selected: object = document.get("selected")
    answer: object = document.get("answer")
    if not (
        document.get("profile") == profile
        and isinstance(revision, str)
        and _REVISION.fullmatch(revision) is not None
        and isinstance(classification, dict)
        and classification.get("contract") == _CLASSIFICATION_CONTRACT
        and isinstance(selected, dict)
        and isinstance(answer, str)
    ):
        _malformed()
    classifier: str = _model(classification.get("model"))
    selected_model: str = _model(selected.get("model"))
    scores: tuple[LabelScore, ...] = _scores(classification.get("scores"))
    selected_label: object = selected.get("label")
    top: float = max(item.score for item in scores)
    leaders: list[str] = [item.label for item in scores if item.score == top]
    # INVARIANT (`unique-argmax-v1`): the selected label is the one label with the highest score.
    if leaders != [selected_label]:
        _malformed()
    return RoutedAnswer(
        profile=profile,
        revision=revision,
        policy=_EXPECTED["policy"],
        contract=_EXPECTED["contract"],
        classifier=classifier,
        scores=scores,
        selected_label=leaders[0],
        selected_model=selected_model,
        answer=answer,
    )


def _model(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    _malformed()


def _scores(value: object) -> tuple[LabelScore, ...]:
    if not isinstance(value, list) or not value:
        _malformed()
    scores: tuple[LabelScore, ...] = tuple(_label_score(item) for item in value)
    if len({item.label for item in scores}) != len(scores):
        _malformed()
    return scores


def _label_score(item: object) -> LabelScore:
    label: object = item.get("label") if isinstance(item, dict) else None
    score: float | None = finite_float(item.get("score")) if isinstance(item, dict) else None
    if isinstance(label, str) and label and score is not None and 0.0 <= score <= 1.0:
        return LabelScore(label=label, score=score)
    _malformed()


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine answered the routed answer with a malformed result",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = ["ROUTE_ANSWER_PATH", "route_answer"]
