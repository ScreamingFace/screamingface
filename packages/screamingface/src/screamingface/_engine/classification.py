"""Classify one text through the Engine's ``/classify`` endpoint (OME-1796).

Stage 1 - build ``/classify?q=(<context>)!classify`` and refuse it before any request when a
    value cannot be encoded as UTF-8 or the encoded path and query pass the Engine's 8 KiB limit.
Stage 2 - one GET that states its wait and is never marked safe to replay, read with a bound.
    A ``303`` is followed only to the Engine's signed artifact path, and that fetch is sent once
    more only after the auth layer finished an Access login for it.
Stage 3 - decode the result, or raise the error the Engine's answer names.

Stages 1 and 2 are the shared direct GET (``_engine/direct_get.py``, OME-1823); this module keeps
the classification's wording, its refusal table and its decoder.

INVARIANT: a classification is a paid call, so nothing here re-sends it. The auth layer re-sends
only a request marked safe to replay, and ``get`` never marks one.
INVARIANT: an error is retryable only when nothing ran: a connect-phase failure, a rate limit, or
the Engine's refusal at admission. A failure once the request may have run, and any failure to
read the result of a run, is not retryable, because classifying again runs the classifier again
and may bill it again.
"""

from __future__ import annotations

import json
from typing import NoReturn

import httpx

from screamingface._engine.direct_get import (
    REQUEST_LIMIT_BYTES,
    DirectCall,
    EngineGet,
    encode_call,
    finite_float,
    get_body,
    result_unavailable,
    url4_error,
)
from screamingface.classification import Classification, LabelScore
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    ExecutionError,
    PlanningError,
)

CLASSIFY_PATH = "/classify"
_INTENT = "classify"
#: WHY a stated wait: the Engine waits min(the request's wait, its `sync_max_wait_s`), and that
#: limit is configurable, 30 s by default and 60 allowed. Stating the wait keeps the Engine's
#: bound at or under 30 s whatever the server's setting, so the read timeout always outlasts it.
_WAIT_S = 30
_RERUN_HINT = "Classifying again runs the classifier again and may bill it again."
_CALL = DirectCall(
    noun="classification",
    verb="classify",
    outcome_code="classification_outcome_unknown",
    wait_s=_WAIT_S,
    rerun_hint=_RERUN_HINT,
)
#: The statuses of a refusal the caller can only fix by changing the request.
_REFUSAL_STATUSES = frozenset({400, 404, 414})
#: The Engine's code for a run that finished but whose result it can no longer serve.
_RESULT_UNAVAILABLE = "result_unavailable"


def classify(get: EngineGet, engine_url: str, model: str, text: str) -> Classification:
    """The labels and scores ``model`` gives ``text``, in the classifier's order.

    e.g. ``classify(client._engine_get, url, "byom_<id>/classifier_v1", "Great service")`` gives
    ``Classification(..., scores=(LabelScore("POSITIVE", 0.98), LabelScore("NEGATIVE", 0.02)))``.
    """

    # Stage 1 - a request the Engine will take.
    path: str = classify_path(model, text)
    # Stage 2 - one call, and at most one artifact fetch.
    body: bytes = get_body(_CALL, get, engine_url, path, _raise_refusal)
    # Stage 3 - the result, checked.
    return _decode(body)


def classify_path(model: str, text: str) -> str:
    """``/classify?q=(<context>)!classify`` for ``model`` and ``text``, within the Engine's limit.

    The context is the exact two-field JSON object the Engine requires.
    """

    if not isinstance(model, str) or not isinstance(text, str):
        raise TypeError("classify takes a model ID and an input text, both str")
    return encode_call(
        _CALL,
        CLASSIFY_PATH,
        _INTENT,
        {"model": ("model ID", model), "input": ("input text", text)},
    )


def _nothing_ran(status: int, headers: httpx.Headers) -> bool:
    """Whether the answer states that the classification never started.

    WHY these two: a rate limiter answers `429` before the request reaches a run (a Gateway or
    provider `429` inside a run reaches the caller as `502`); the Engine's run admission answers
    `503` with `Retry-After` when its runner is at capacity or its queue is unavailable, and
    states that nothing was queued. A queue-unavailable `503` after a publish whose
    acknowledgement was lost may still have stored the run; that Engine-wide gap is open (spec
    section 8). Every other `503` may come from a run that started, url4's
    `x.admission_timeout` included: only an expression's `;t=` guard raises it, and `/classify`
    runs none, so on this call it is relayed from inside a run.
    """

    return status == 429 or (status == 503 and "Retry-After" in headers)


def _raise_refusal(status: int, headers: httpx.Headers, body: bytes) -> NoReturn:
    error: tuple[str, str] | None = url4_error(body)
    if error is None and status == 404:
        # WHY by the envelope: an Engine without `/classify` answers its framework's plain 404,
        # while an Engine that serves it answers a missing classifier with url4's envelope.
        raise EngineCapabilityError(
            "this SF Engine does not serve /classify",
            status=404,
            permanent=True,
            details={"path": CLASSIFY_PATH},
            hint="Use an SF Engine that serves /classify, or update the local Engine.",
        )
    code, message = error if error is not None else (None, f"HTTP {status}")
    if code == _RESULT_UNAVAILABLE:
        # WHY before the refusal statuses: the Engine answers it, as `404` too, for a run that
        # finished and whose result it can no longer serve. The classifier ran and billed.
        raise result_unavailable(_CALL, status)
    if status in (401, 403):
        raise AuthenticationError(
            f"The SF Engine refused the caller: {message}", code=code, status=status, permanent=True
        )
    if status in _REFUSAL_STATUSES:
        raise PlanningError(
            f"The SF Engine refused the classification: {message}",
            code=code,
            status=status,
            permanent=True,
        )
    if _nothing_ran(status, headers):
        raise ExecutionError(
            f"The SF Engine did not start the classification: {message}",
            code=code,
            status=status,
            permanent=False,
        )
    if status >= 500:
        # INVARIANT: the Engine answers `502` for a permanent refusal and a transient failure
        # alike, and a run it stopped may already have called the classifier.
        raise ExecutionError(
            f"The classification did not finish and may have run and been billed: {message}",
            code=code,
            status=status,
            permanent=True,
            hint=_RERUN_HINT,
        )
    raise ExecutionError(
        f"The classification did not finish: {message}",
        code=code,
        status=status,
        permanent=True,
    )


def _decode(body: bytes) -> Classification:
    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError):
        _malformed()
    if not isinstance(document, dict) or document.get("object") != "classification":
        _malformed()
    model: object = document.get("model")
    contract: object = document.get("contract")
    scores: object = document.get("scores")
    if not (isinstance(model, str) and isinstance(contract, str) and isinstance(scores, list)):
        _malformed()
    if not scores:
        _malformed()
    return Classification(
        model=model, contract=contract, scores=tuple(_label_score(item) for item in scores)
    )


def _label_score(item: object) -> LabelScore:
    label: object = item.get("label") if isinstance(item, dict) else None
    score: float | None = finite_float(item.get("score")) if isinstance(item, dict) else None
    # WHY no range check: the Engine checks each score against its target's score semantics
    # before it answers; this decoder checks only that the answer is well formed.
    if isinstance(label, str) and label and score is not None:
        return LabelScore(label=label, score=score)
    _malformed()


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine answered the classification with a malformed result",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = ["CLASSIFY_PATH", "REQUEST_LIMIT_BYTES", "EngineGet", "classify", "classify_path"]
