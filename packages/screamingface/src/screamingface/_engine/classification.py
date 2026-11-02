"""Classify one text through the Engine's ``/classify`` endpoint (OME-1796).

Stage 1 - build ``/classify?q=(<context>)!classify`` and refuse it before any request when a
    value cannot be encoded as UTF-8 or the encoded path and query pass the Engine's 8 KiB limit.
Stage 2 - one GET that states its wait and is never marked safe to replay, read with a bound.
    A ``303`` is followed only to the Engine's signed artifact path, and that fetch is sent once
    more only after the auth layer finished an Access login for it.
Stage 3 - decode the result, or raise the error the Engine's answer names.

INVARIANT: a classification is a paid call, so nothing here re-sends it. The auth layer re-sends
only a request marked safe to replay, and ``get`` never marks one.
INVARIANT: an error is retryable only when nothing ran: a connect-phase failure, a rate limit, or
the Engine's refusal at admission. A failure once the request may have run, and any failure to
read the result of a run, is not retryable, because classifying again runs the classifier again
and may bill it again.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import NoReturn, Protocol

import httpx
from url4.wire.subrequest import encode_subrequest

from screamingface.classification import Classification, LabelScore
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
    ScreamingFaceError,
)

CLASSIFY_PATH = "/classify"
_INTENT = "classify"
#: The Engine's own limit on a direct call's encoded path and query; one byte more answers 414.
REQUEST_LIMIT_BYTES = 8 * 1024
#: WHY a stated wait: the Engine waits min(the request's wait, its `sync_max_wait_s`), and that
#: limit is configurable, 30 s by default and 60 allowed. Stating the wait keeps the Engine's
#: bound at or under 30 s whatever the server's setting, so the read timeout always outlasts it.
_WAIT_S = 30
_PREFER: Mapping[str, str] = {"Prefer": f"wait={_WAIT_S}"}
#: WHY 15 s over the wait: at its bound the Engine stops the run and answers `504 timeout`; the
#: margin lets that answer arrive instead of a client timeout.
_TIMEOUT = httpx.Timeout(30.0, read=_WAIT_S + 15.0)
#: WHY 2 MiB: the Engine inlines a result up to 1 MiB and spills a larger one to an artifact,
#: and the Gateway reads at most 1 MB from the classifier, so a real answer stays well below.
_READ_LIMIT_BYTES = 2 * 1024 * 1024
_CHUNK_BYTES = 65536
#: The spill `Location` exactly as the Engine's `signed_artifact_path` writes it: one content
#: address on the artifact route, then the expiry and the signature.
#: WHY matched as it arrived: httpx resolves dot segments, so `/artifacts/../classify` passes a
#: prefix check and becomes a second `/classify`. No dot, `%`, slash, scheme or host fits here.
_ARTIFACT_LOCATION = re.compile(r"/artifacts/[0-9a-f]+\?exp=[0-9]+&sig=[A-Za-z0-9_-]+")
#: The statuses of a refusal the caller can only fix by changing the request.
_REFUSAL_STATUSES = frozenset({400, 404, 414})
#: The transport failures raised before the request left the client.
_NEVER_SENT: tuple[type[httpx.TransportError], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)
#: The Engine's code for a run that finished but whose result it can no longer serve.
_RESULT_UNAVAILABLE = "result_unavailable"
#: The auth layer's code once it has finished an Access login for a request it will not re-send.
_REAUTHENTICATED = "access_reauthenticated"
_RERUN_HINT = "Classifying again runs the classifier again and may bill it again."


class EngineGet(Protocol):
    """A streamed GET on the Engine that is never marked safe to replay (``Client._engine_get``)."""

    def __call__(
        self, path: str, *, headers: Mapping[str, str], timeout: httpx.Timeout
    ) -> AbstractContextManager[httpx.Response]: ...


def classify(get: EngineGet, engine_url: str, model: str, text: str) -> Classification:
    """The labels and scores ``model`` gives ``text``, in the classifier's order.

    e.g. ``classify(client._engine_get, url, "byom_<id>/classifier_v1", "Great service")`` gives
    ``Classification(..., scores=(LabelScore("POSITIVE", 0.98), LabelScore("NEGATIVE", 0.02)))``.
    """

    # Stage 1 - a request the Engine will take.
    path: str = classify_path(model, text)
    # Stage 2 - one call, and at most one artifact fetch.
    try:
        status, headers, body = _read(get, path)
    except _NEVER_SENT as exc:
        raise EngineUnavailableError(
            "Could not reach the SF Engine to classify", engine_url=engine_url
        ) from exc
    except httpx.HTTPError as exc:
        raise _outcome_unknown() from exc
    if status == 303:
        body = _artifact(get, headers.get("Location", ""))
    elif status != 200:
        _raise_refusal(status, headers, body)
    # Stage 3 - the result, checked.
    return _decode(body)


def classify_path(model: str, text: str) -> str:
    """``/classify?q=(<context>)!classify`` for ``model`` and ``text``, within the Engine's limit.

    The context is the exact two-field JSON object the Engine requires; the url4 encoder escapes
    ``+``, ``&``, quotes and newlines so the text arrives byte for byte.
    """

    if not isinstance(model, str) or not isinstance(text, str):
        raise TypeError("classify takes a model ID and an input text, both str")
    for field, value in (("model ID", model), ("input text", text)):
        if not _utf8_encodable(value):
            # INVARIANT: the refusal names the field, never the value; it is raised outside the
            # encoder's own error, whose `object` would carry the whole text.
            raise PlanningError(
                f"The classification {field} holds a character that UTF-8 cannot encode",
                code="malformed_source",
                permanent=True,
                hint="Remove unpaired surrogate characters; the SF Engine refuses them too.",
            )
    context: str = json.dumps(
        {"model": model, "input": text}, ensure_ascii=False, separators=(",", ":")
    )
    path: str = encode_subrequest(CLASSIFY_PATH, context, _INTENT)
    # WHY measured through httpx: it percent-encodes non-ASCII text on the wire, and the
    # Engine counts those bytes, not characters.
    size: int = len(httpx.URL(path).raw_path)
    if size > REQUEST_LIMIT_BYTES:
        raise PlanningError(
            f"The classification request is {size} bytes once encoded; the SF Engine takes at "
            f"most {REQUEST_LIMIT_BYTES}",
            code="uri_too_long",
            permanent=True,
            details={"encoded_bytes": size, "limit_bytes": REQUEST_LIMIT_BYTES},
            hint="Shorten the input. Quotes and non-ASCII text take several bytes per character "
            "once encoded.",
        )
    return path


def _utf8_encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _read(get: EngineGet, path: str) -> tuple[int, httpx.Headers, bytes]:
    """One GET: its status, its headers and its body, never more than the read limit.

    Raises ``httpx.HTTPError`` unchanged; the caller knows whether the classification has run.
    """

    with get(path, headers=_PREFER, timeout=_TIMEOUT) as response:
        return response.status_code, response.headers, _bounded(response)


def _bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    received: int = 0
    for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
        received += len(chunk)
        if received > _READ_LIMIT_BYTES:
            raise ExecutionError(
                f"The SF Engine answer passed the {_READ_LIMIT_BYTES} byte classification limit",
                code="result_too_large",
                status=response.status_code,
                permanent=True,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _artifact_path(location: str) -> str:
    # INVARIANT: only the Engine's own signed artifact path is followed, so a redirect can never
    # carry the caller's credentials to another origin or send the classification again.
    if _ARTIFACT_LOCATION.fullmatch(location) is None:
        raise ExecutionError(
            "The SF Engine redirected the classification off its artifact path",
            code="engine_contract_error",
            status=303,
            permanent=True,
        )
    return location


def _artifact(get: EngineGet, location: str) -> bytes:
    """The result the Engine spilled to an artifact, after a classification that has run.

    INVARIANT: every failure here is `result_unavailable` and not retryable, a connect-phase one
    included. Fetching the result again and classifying again are different acts, and only the
    second one runs and bills the classifier.
    """

    path: str = _artifact_path(location)
    try:
        status, _, body = _read_artifact(get, path)
    except (httpx.HTTPError, ScreamingFaceError) as exc:
        raise _result_unavailable(None) from exc
    if status != 200:
        raise _result_unavailable(status)
    return body


def _read_artifact(get: EngineGet, path: str) -> tuple[int, httpx.Headers, bytes]:
    try:
        return _read(get, path)
    except AuthenticationError as exc:
        if exc.code != _REAUTHENTICATED:
            raise
    # WHY once more, and only here: Access stops a challenged request at its edge, so this fetch
    # never reached the Engine, and reading a stored result bills nothing. The login is done; the
    # classification itself is still never sent again.
    return _read(get, path)


def _result_unavailable(status: int | None) -> ExecutionError:
    reason: str = "" if status is None else f": HTTP {status}"
    return ExecutionError(
        f"The classification ran, but its result could not be read from the SF Engine{reason}",
        code="result_unavailable",
        status=status,
        permanent=True,
        hint=_RERUN_HINT,
    )


def _outcome_unknown() -> ExecutionError:
    # WHY not EngineUnavailableError: that error says the Engine was not reached, which makes a
    # retry safe. Here the request was sent, so the classification may have run.
    return ExecutionError(
        "The connection to the SF Engine failed after the classification was sent; it may have "
        "run and been billed",
        code="classification_outcome_unknown",
        permanent=True,
        hint=_RERUN_HINT,
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
    error: tuple[str, str] | None = _url4_error(body)
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
        raise _result_unavailable(status)
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


def _url4_error(body: bytes) -> tuple[str, str] | None:
    """url4's ``{"error": {"code", "message"}}`` envelope, when ``body`` is one."""

    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError):
        return None
    error: object = document.get("error") if isinstance(document, dict) else None
    if isinstance(error, dict):
        code, message = error.get("code"), error.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return code, message
    return None


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
    score: float | None = _finite_float(item.get("score")) if isinstance(item, dict) else None
    # WHY no range check: the Engine checks each score against its target's score semantics
    # before it answers; this decoder checks only that the answer is well formed.
    if isinstance(label, str) and label and score is not None:
        return LabelScore(label=label, score=score)
    _malformed()


def _finite_float(value: object) -> float | None:
    """``value`` as a finite float, or None when it is not a JSON number that fits one."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        number: float = float(value)
    except OverflowError:
        # WHY: JSON integers are unbounded, so one past the float range is a malformed score.
        return None
    return number if math.isfinite(number) else None


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine answered the classification with a malformed result",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = ["CLASSIFY_PATH", "REQUEST_LIMIT_BYTES", "EngineGet", "classify", "classify_path"]
