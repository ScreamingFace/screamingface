"""The Engine capability reader: the one strict codec of ``GET /v1/capabilities`` (C12).

FEATURE: the capability gate. A plan that needs an Engine capability is refused before anything
is minted, registered or run when the Engine does not advertise it. The runner calls ``require``
only for a plan that needs at least one ID; today no public caller does.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx

from screamingface._engine.catalog import _unreachable
from screamingface.errors import AuthenticationError, EngineCapabilityError

_CAPABILITIES_PATH = "/v1/capabilities"
_OBJECT = "engine_capabilities"
_CONTRACT = "engine-capabilities-v1"
_KEYS = frozenset({"object", "contract", "capabilities"})
_LABEL = "capabilities"


class EngineCapabilities:
    """Synchronous capability reader bound to one Client's Engine GET.

    INVARIANT (C12): every call reads the Engine afresh, with no cache, ETag or stale copy, so an
    ID the fleet withdrew refuses the next submission.
    """

    def __init__(self, get: Callable[[str], httpx.Response], engine_url: str) -> None:
        self._get = get
        self._engine_url = engine_url

    def require(self, required: frozenset[str]) -> None:
        """Refuse unless the Engine advertises every ID in ``required``."""

        try:
            response = self._get(_CAPABILITIES_PATH)
        except httpx.HTTPError as exc:
            _unreachable(self._engine_url, _LABEL, exc)
        _require(required, _advertised(response))


class AsyncEngineCapabilities:
    """Asynchronous twin of ``EngineCapabilities``."""

    def __init__(self, get: Callable[[str], Awaitable[httpx.Response]], engine_url: str) -> None:
        self._get = get
        self._engine_url = engine_url

    async def require(self, required: frozenset[str]) -> None:
        """Refuse unless the Engine advertises every ID in ``required``."""

        try:
            response = await self._get(_CAPABILITIES_PATH)
        except httpx.HTTPError as exc:
            _unreachable(self._engine_url, _LABEL, exc)
        _require(required, _advertised(response))


def decode_capabilities(body: bytes) -> frozenset[str]:
    """The advertised IDs of one ``engine-capabilities-v1`` document; anything else is refused.

    INVARIANT (C12): the object is closed, with no repeated key, and its list holds unique
    nonempty strings in lexical order. Unknown IDs are kept; only a required one matters.
    """

    try:
        document = json.loads(body, object_pairs_hook=_without_repeated_keys)
    except (ValueError, RecursionError) as exc:
        # WHY RecursionError: the stdlib decoder raises it, not a ValueError, for nesting deeper
        # than the interpreter's limit, and a bad answer must still read as a contract error.
        raise _invalid("is not JSON") from exc
    if not isinstance(document, dict) or document.keys() != _KEYS:
        raise _invalid("must hold exactly object, contract and capabilities")
    if document["object"] != _OBJECT or document["contract"] != _CONTRACT:
        raise _invalid(f"must be {_OBJECT!r} under {_CONTRACT!r}")
    ids = document["capabilities"]
    if not isinstance(ids, list) or not all(isinstance(id_, str) and id_ for id_ in ids):
        raise _invalid("must list capabilities as nonempty strings")
    if ids != sorted(set(ids)):
        raise _invalid("must list each capability once, in lexical order")
    return frozenset(ids)


def _advertised(response: httpx.Response) -> frozenset[str]:
    # INVARIANT (C12): an auth failure keeps the category the Model catalogue gives it; every
    # other answer that is not the document is missing discovery.
    if response.status_code in {401, 403}:
        raise AuthenticationError(
            f"SF Engine authentication is required for {_LABEL}",
            code="authentication_required",
            status=response.status_code,
            permanent=True,
        )
    if response.status_code == 404:
        raise EngineCapabilityError(
            "this SF Engine does not publish its capabilities",
            status=404,
            permanent=True,
            details={"path": _CAPABILITIES_PATH},
            hint="Use an SF Engine that serves GET /v1/capabilities.",
        )
    if not response.is_success:
        raise EngineCapabilityError(
            f"Could not read the SF Engine capabilities: HTTP {response.status_code}",
            status=response.status_code,
            permanent=response.status_code < 500,
            details={"path": _CAPABILITIES_PATH},
        )
    return decode_capabilities(response.content)


def _require(required: frozenset[str], advertised: frozenset[str]) -> None:
    missing = sorted(required - advertised)
    if missing:
        raise EngineCapabilityError(
            f"this SF Engine does not support {', '.join(missing)}",
            permanent=True,
            details={"path": _CAPABILITIES_PATH, "missing": missing},
            hint="Use an SF Engine whose fleet advertises these capabilities.",
        )


def _without_repeated_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise _invalid("repeats a key")
    return document


def _invalid(reason: str) -> EngineCapabilityError:
    return EngineCapabilityError(
        f"SF Engine capabilities document {reason}",
        code="engine_contract_error",
        permanent=True,
        details={"path": _CAPABILITIES_PATH},
    )


__all__ = ["AsyncEngineCapabilities", "EngineCapabilities", "decode_capabilities"]
