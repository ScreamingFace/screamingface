"""One paid GET on an Engine direct mount, shared by ``classify`` and ``route_answer``.

Moved from ``_engine/classification.py`` without a change of behavior (OME-1823): each call
names itself through a ``DirectCall``, so ``classify`` keeps its exact messages, codes and
timeouts, and ``route_answer`` gets its own.

Stage 1 - build ``<route>?q=(<context>)!<intent>`` and refuse it before any request when a value
    cannot be encoded as UTF-8 or the encoded path and query pass the Engine's 8 KiB limit.
Stage 2 - one GET that states its wait and is never marked safe to replay, read with a bound.
    A ``303`` is followed only to the Engine's signed artifact path, and that fetch is sent once
    more only after the auth layer finished an Access login for it.
Stage 3 - the caller decodes the body, or raises the error its own refusal table names.

INVARIANT: a direct call is paid, so nothing here re-sends it. The auth layer re-sends only a
request marked safe to replay, and an ``EngineGet`` never marks one.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import NoReturn, Protocol

import httpx
from url4.wire.subrequest import encode_subrequest

from screamingface.errors import (
    AuthenticationError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
    ScreamingFaceError,
)

#: The Engine's own limit on a direct call's encoded path and query; one byte more answers 414.
REQUEST_LIMIT_BYTES = 8 * 1024
#: WHY 2 MiB: the Engine inlines a result up to 1 MiB and spills a larger one to an artifact,
#: and the Gateway reads at most 1 MB from the classifier, so a real answer stays well below.
_READ_LIMIT_BYTES = 2 * 1024 * 1024
_CHUNK_BYTES = 65536
#: The spill `Location` exactly as the Engine's `signed_artifact_path` writes it: one content
#: address on the artifact route, then the expiry and the signature.
#: WHY matched as it arrived: httpx resolves dot segments, so `/artifacts/../classify` passes a
#: prefix check and becomes a second `/classify`. No dot, `%`, slash, scheme or host fits here.
_ARTIFACT_LOCATION = re.compile(r"/artifacts/[0-9a-f]+\?exp=[0-9]+&sig=[A-Za-z0-9_-]+")
#: The transport failures raised before the request left the client.
_NEVER_SENT: tuple[type[httpx.TransportError], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)
#: The auth layer's code once it has finished an Access login for a request it will not re-send.
_REAUTHENTICATED = "access_reauthenticated"


class EngineGet(Protocol):
    """A streamed GET on the Engine that is never marked safe to replay (``Client._engine_get``)."""

    def __call__(
        self, path: str, *, headers: Mapping[str, str], timeout: httpx.Timeout
    ) -> AbstractContextManager[httpx.Response]: ...


Refuse = Callable[[int, httpx.Headers, bytes], NoReturn]
"""A call's own refusal table: the error for a status other than ``200`` and ``303``."""


@dataclass(frozen=True)
class DirectCall:
    """How one kind of direct call names itself and how long it waits.

    e.g. ``DirectCall("classification", "classify", "classification_outcome_unknown", 30, hint)``
    gives "The classification ran, but its result could not be read from the SF Engine".
    """

    noun: str
    verb: str
    outcome_code: str
    wait_s: int
    rerun_hint: str

    @property
    def headers(self) -> Mapping[str, str]:
        return {"Prefer": f"wait={self.wait_s}"}

    @property
    def timeout(self) -> httpx.Timeout:
        # WHY 15 s over the wait: at its bound the Engine stops the run and answers `504
        # timeout`; the margin lets that answer arrive instead of a client timeout.
        return httpx.Timeout(30.0, read=self.wait_s + 15.0)


def encode_call(
    call: DirectCall, route: str, intent: str, fields: Mapping[str, tuple[str, str]]
) -> str:
    """``<route>?q=(<context>)!<intent>``, the context holding exactly ``fields``' values.

    ``fields`` maps each context key to its name in messages and its value. The url4 encoder
    escapes ``+``, ``&``, quotes and newlines so every value arrives byte for byte.
    """

    for name, value in fields.values():
        if not _utf8_encodable(value):
            # INVARIANT: the refusal names the field, never the value; it is raised outside the
            # encoder's own error, whose `object` would carry the whole text.
            raise PlanningError(
                f"The {call.noun} {name} holds a character that UTF-8 cannot encode",
                code="malformed_source",
                permanent=True,
                hint="Remove unpaired surrogate characters; the SF Engine refuses them too.",
            )
    context: str = json.dumps(
        {key: value for key, (_, value) in fields.items()},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    path: str = encode_subrequest(route, context, intent)
    # WHY measured through httpx: it percent-encodes non-ASCII text on the wire, and the
    # Engine counts those bytes, not characters.
    size: int = len(httpx.URL(path).raw_path)
    if size > REQUEST_LIMIT_BYTES:
        raise PlanningError(
            f"The {call.noun} request is {size} bytes once encoded; the SF Engine takes at "
            f"most {REQUEST_LIMIT_BYTES}",
            code="uri_too_long",
            permanent=True,
            details={"encoded_bytes": size, "limit_bytes": REQUEST_LIMIT_BYTES},
            hint="Shorten the input. Quotes and non-ASCII text take several bytes per character "
            "once encoded.",
        )
    return path


def get_body(call: DirectCall, get: EngineGet, engine_url: str, path: str, refuse: Refuse) -> bytes:
    """The result body of one call to ``path``, fetched from its artifact when spilled."""

    try:
        status, headers, body = _read(call, get, path)
    except _NEVER_SENT as exc:
        raise EngineUnavailableError(
            f"Could not reach the SF Engine to {call.verb}", engine_url=engine_url
        ) from exc
    except httpx.HTTPError as exc:
        raise _outcome_unknown(call) from exc
    if status == 303:
        return _artifact(call, get, headers.get("Location", ""))
    if status != 200:
        refuse(status, headers, body)
    return body


def _utf8_encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _read(call: DirectCall, get: EngineGet, path: str) -> tuple[int, httpx.Headers, bytes]:
    """One GET: its status, its headers and its body, never more than the read limit.

    Raises ``httpx.HTTPError`` unchanged; the caller knows whether the call has run.
    """

    with get(path, headers=call.headers, timeout=call.timeout) as response:
        return response.status_code, response.headers, _bounded(call, response)


def _bounded(call: DirectCall, response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    received: int = 0
    for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
        received += len(chunk)
        if received > _READ_LIMIT_BYTES:
            raise ExecutionError(
                f"The SF Engine answer passed the {_READ_LIMIT_BYTES} byte {call.noun} limit",
                code="result_too_large",
                status=response.status_code,
                permanent=True,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _artifact_path(call: DirectCall, location: str) -> str:
    # INVARIANT: only the Engine's own signed artifact path is followed, so a redirect can never
    # carry the caller's credentials to another origin or send the call again.
    if _ARTIFACT_LOCATION.fullmatch(location) is None:
        raise ExecutionError(
            f"The SF Engine redirected the {call.noun} off its artifact path",
            code="engine_contract_error",
            status=303,
            permanent=True,
        )
    return location


def _artifact(call: DirectCall, get: EngineGet, location: str) -> bytes:
    """The result the Engine spilled to an artifact, after a call that has run.

    INVARIANT: every failure here is `result_unavailable` and not retryable, a connect-phase one
    included. Fetching the result again and calling again are different acts, and only the
    second one runs and bills a model.
    """

    path: str = _artifact_path(call, location)
    try:
        status, _, body = _read_artifact(call, get, path)
    except (httpx.HTTPError, ScreamingFaceError) as exc:
        raise result_unavailable(call, None) from exc
    if status != 200:
        raise result_unavailable(call, status)
    return body


def _read_artifact(call: DirectCall, get: EngineGet, path: str) -> tuple[int, httpx.Headers, bytes]:
    try:
        return _read(call, get, path)
    except AuthenticationError as exc:
        if exc.code != _REAUTHENTICATED:
            raise
    # WHY once more, and only here: Access stops a challenged request at its edge, so this fetch
    # never reached the Engine, and reading a stored result bills nothing. The login is done; the
    # call itself is still never sent again.
    return _read(call, get, path)


def result_unavailable(call: DirectCall, status: int | None) -> ExecutionError:
    reason: str = "" if status is None else f": HTTP {status}"
    return ExecutionError(
        f"The {call.noun} ran, but its result could not be read from the SF Engine{reason}",
        code="result_unavailable",
        status=status,
        permanent=True,
        hint=call.rerun_hint,
    )


def _outcome_unknown(call: DirectCall) -> ExecutionError:
    # WHY not EngineUnavailableError: that error says the Engine was not reached, which makes a
    # retry safe. Here the request was sent, so the call may have run.
    return ExecutionError(
        f"The connection to the SF Engine failed after the {call.noun} was sent; it may have "
        "run and been billed",
        code=call.outcome_code,
        permanent=True,
        hint=call.rerun_hint,
    )


def url4_error(body: bytes) -> tuple[str, str] | None:
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


def finite_float(value: object) -> float | None:
    """``value`` as a finite float, or None when it is not a JSON number that fits one."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        number: float = float(value)
    except OverflowError:
        # WHY: JSON integers are unbounded, so one past the float range is a malformed score.
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "REQUEST_LIMIT_BYTES",
    "DirectCall",
    "EngineGet",
    "Refuse",
    "encode_call",
    "finite_float",
    "get_body",
    "result_unavailable",
    "url4_error",
]
