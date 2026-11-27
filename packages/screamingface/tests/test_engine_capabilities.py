"""The Engine capability reader: one strict codec and a fresh read per call (C12, Unit 6).

FEATURE: the capability gate. An Evaluation that needs an Engine capability is refused when the
Engine does not advertise it, before anything is minted, registered or run.
STORY: as a researcher whose Engine has not rolled a capability out yet, my Evaluation that needs
it is refused at once, with the missing ID named, and nothing is spent.

INVARIANT: the document is closed and strict. Every read goes to the Engine: no cache, no ETag
and no stale copy. An auth or transport failure keeps the category the rest of the Client gives
it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest

import screamingface as sf
from screamingface._engine.capabilities import decode_capabilities
from screamingface.errors import AuthenticationError, EngineCapabilityError, EngineUnavailableError

_BASE = "https://engine.example"
_PATH = "/v1/capabilities"
_DORMANT = b'{"object":"engine_capabilities","contract":"engine-capabilities-v1","capabilities":[]}'
_HEAD = b'{"object":"engine_capabilities","contract":"engine-capabilities-v1",'
_ROUTER = frozenset({"router-v1"})
# A stand-in for a transport failure in an answer script.
_UNREACHABLE = "unreachable"

type _Answer = httpx.Response | str


def _document(*ids: str) -> httpx.Response:
    body = {"object": "engine_capabilities", "contract": "engine-capabilities-v1"}
    return httpx.Response(200, json={**body, "capabilities": list(ids)})


# --- the codec ---------------------------------------------------------------------------------


def test_the_dormant_document_is_the_empty_set() -> None:
    advertised = decode_capabilities(_DORMANT)

    assert advertised == frozenset()
    assert type(advertised) is frozenset


def test_whitespace_between_tokens_is_still_the_document() -> None:
    spaced = json.dumps(json.loads(_DORMANT), indent=2).encode()

    assert decode_capabilities(spaced) == frozenset()


def test_unique_ids_in_lexical_order_decode() -> None:
    ids = ["classify-frozen-copy-v1", "future-v9", "router-v1"]

    assert decode_capabilities(_document(*ids).content) == frozenset(ids)


_REFUSED: dict[str, bytes] = {
    # INVARIANT (C12): the object is closed, and a repeated key is refused, even with one value.
    "repeated-key": b'{"object":"x","object":"engine_capabilities",'
    b'"contract":"engine-capabilities-v1","capabilities":[]}',
    "repeated-key-same-value": b'{"object":"engine_capabilities","object":"engine_capabilities",'
    b'"contract":"engine-capabilities-v1","capabilities":[]}',
    "repeated-list": _HEAD + b'"capabilities":["router-v1"],"capabilities":[]}',
    "extra-key": _HEAD + b'"capabilities":[],"etag":"x"}',
    "missing-object": b'{"contract":"engine-capabilities-v1","capabilities":[]}',
    "missing-contract": b'{"object":"engine_capabilities","capabilities":[]}',
    "missing-capabilities": b'{"object":"engine_capabilities","contract":"engine-capabilities-v1"}',
    "wrong-object": b'{"object":"engine_capability","contract":"engine-capabilities-v1",'
    b'"capabilities":[]}',
    "wrong-contract": b'{"object":"engine_capabilities","contract":"engine-capabilities-v2",'
    b'"capabilities":[]}',
    "object-not-text": b'{"object":1,"contract":"engine-capabilities-v1","capabilities":[]}',
    "contract-null": b'{"object":"engine_capabilities","contract":null,"capabilities":[]}',
    "list-null": _HEAD + b'"capabilities":null}',
    "list-object": _HEAD + b'"capabilities":{}}',
    "list-text": _HEAD + b'"capabilities":"router-v1"}',
    "id-number": _HEAD + b'"capabilities":[1]}',
    "id-null": _HEAD + b'"capabilities":[null]}',
    "id-true": _HEAD + b'"capabilities":[true]}',
    "id-object": _HEAD + b'"capabilities":[{}]}',
    "id-list": _HEAD + b'"capabilities":[["router-v1"]]}',
    "id-empty": _HEAD + b'"capabilities":[""]}',
    "id-duplicate": _HEAD + b'"capabilities":["router-v1","router-v1"]}',
    "ids-out-of-order": _HEAD + b'"capabilities":["router-v1","classify-frozen-copy-v1"]}',
    "non-finite-id": _HEAD + b'"capabilities":[NaN]}',
    "non-finite-list": _HEAD + b'"capabilities":Infinity}',
    "empty-body": b"",
    "truncated": b'{"object":"engine_capabilities"',
    "trailing-comma": _HEAD + b'"capabilities":["router-v1",]}',
    "top-level-null": b"null",
    "top-level-list": b"[]",
    "top-level-text": b'"engine_capabilities"',
    "bad-utf8": b'{"object":"\xff"}',
    "too-deep": b"[" * 100_000 + b"]" * 100_000,
}


@pytest.mark.parametrize("body", list(_REFUSED.values()), ids=list(_REFUSED))
def test_any_other_document_is_refused_as_a_contract_error(body: bytes) -> None:
    with pytest.raises(EngineCapabilityError) as caught:
        decode_capabilities(body)

    assert caught.value.code == "engine_contract_error"
    assert caught.value.permanent is True
    assert caught.value.details == {"path": _PATH}


# --- the reader, through each Client ------------------------------------------------------------


def _engine(answers: list[_Answer], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = answers.pop(0)
        if isinstance(answer, str):
            raise httpx.ConnectError(answer, request=request)
        return answer

    return httpx.MockTransport(handler)


def _outcomes(
    answers: Sequence[_Answer],
    required: frozenset[str],
    *,
    asynchronous: bool,
    read: Callable[[Any], Any] = lambda client: client._capabilities.require,
) -> tuple[list[sf.ScreamingFaceError | None], list[httpx.Request]]:
    """What each of ``len(answers)`` reads did — None when it passed — and what the Engine saw."""

    seen: list[httpx.Request] = []
    transport = _engine(list(answers), seen)
    if asynchronous:
        return asyncio.run(_async_outcomes(transport, len(answers), required, read)), seen
    outcomes: list[sf.ScreamingFaceError | None] = []
    with sf.Client(engine_url=_BASE, http_transport=transport) as client:
        for _ in answers:
            try:
                read(client)(required)
                outcomes.append(None)
            except sf.ScreamingFaceError as exc:
                outcomes.append(exc)
    return outcomes, seen


async def _async_outcomes(
    transport: httpx.MockTransport,
    count: int,
    required: frozenset[str],
    read: Callable[[Any], Any],
) -> list[sf.ScreamingFaceError | None]:
    outcomes: list[sf.ScreamingFaceError | None] = []
    async with sf.AsyncClient(engine_url=_BASE, http_transport=transport) as client:
        for _ in range(count):
            try:
                await read(client)(required)
                outcomes.append(None)
            except sf.ScreamingFaceError as exc:
                outcomes.append(exc)
    return outcomes


def _only_error(answer: _Answer, *, asynchronous: bool) -> sf.ScreamingFaceError:
    (outcome,), _ = _outcomes([answer], _ROUTER, asynchronous=asynchronous)
    assert outcome is not None
    return outcome


_TWINS = pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])


@_TWINS
def test_every_read_asks_the_engine_afresh(asynchronous: bool) -> None:
    # INVARIANT (C12): a positive answer is never kept; the withdrawn one refuses the next call.
    outcomes, seen = _outcomes(
        [_document("router-v1"), _document()], _ROUTER, asynchronous=asynchronous
    )

    assert outcomes[0] is None
    assert isinstance(outcomes[1], EngineCapabilityError)
    assert [(request.method, request.url.path) for request in seen] == [("GET", _PATH)] * 2
    for request in seen:
        assert "If-None-Match" not in request.headers
        assert "If-Modified-Since" not in request.headers


@_TWINS
def test_a_missing_id_is_named_and_nothing_else_is_asked(asynchronous: bool) -> None:
    required = frozenset({"router-v1", "router-placement-v1"})

    (error,), seen = _outcomes(
        [_document("classify-frozen-copy-v1", "router-v1")], required, asynchronous=asynchronous
    )

    assert isinstance(error, EngineCapabilityError)
    assert error.code == "engine_capability_missing"
    assert error.permanent is True
    assert error.status is None
    assert error.details == {"path": _PATH, "missing": ["router-placement-v1"]}
    assert "router-placement-v1" in error.message
    assert len(seen) == 1


@_TWINS
def test_unknown_ids_are_ignored_and_every_required_one_must_be_there(asynchronous: bool) -> None:
    required = frozenset({"classify-frozen-copy-v1", "router-v1"})

    outcomes, _ = _outcomes(
        [_document("classify-frozen-copy-v1", "future-v9", "router-v1")],
        required,
        asynchronous=asynchronous,
    )

    assert outcomes == [None]


@_TWINS
def test_an_engine_without_discovery_lacks_the_capability(asynchronous: bool) -> None:
    error = _only_error(httpx.Response(404), asynchronous=asynchronous)

    assert isinstance(error, EngineCapabilityError)
    assert error.code == "engine_capability_missing"
    assert (error.status, error.permanent) == (404, True)
    assert error.details == {"path": _PATH}
    assert error.hint is not None and "GET /v1/capabilities" in error.hint


@_TWINS
@pytest.mark.parametrize(("status", "permanent"), [(400, True), (500, False), (503, False)])
def test_any_other_answer_is_missing_discovery(
    asynchronous: bool, status: int, permanent: bool
) -> None:
    # WHY retryable only from 500 up: the same read may succeed once the Engine recovers, and no
    # submission was made either way.
    error = _only_error(httpx.Response(status), asynchronous=asynchronous)

    assert isinstance(error, EngineCapabilityError)
    assert error.code == "engine_capability_missing"
    assert (error.status, error.permanent) == (status, permanent)


@_TWINS
def test_a_document_that_is_not_the_contract_is_refused(asynchronous: bool) -> None:
    error = _only_error(httpx.Response(200, content=b"not json"), asynchronous=asynchronous)

    assert isinstance(error, EngineCapabilityError)
    assert error.code == "engine_contract_error"


@_TWINS
@pytest.mark.parametrize("answer", [401, 403, _UNREACHABLE], ids=["401", "403", "down"])
def test_auth_and_transport_failures_keep_the_category_the_catalogue_gives(
    asynchronous: bool, answer: int | str
) -> None:
    # INVARIANT (C12): an auth or transport failure is never turned into a missing capability.
    # WHY a fresh Response per read: a Response a Client already read cannot be served again.
    def scripted() -> _Answer:
        return answer if isinstance(answer, str) else httpx.Response(answer)

    error = _only_error(scripted(), asynchronous=asynchronous)
    (catalogue,), _ = _outcomes(
        [scripted()], _ROUTER, asynchronous=asynchronous, read=lambda client: _listing(client)
    )

    assert catalogue is not None
    assert not isinstance(error, EngineCapabilityError)
    assert isinstance(error, AuthenticationError | EngineUnavailableError)
    assert (type(error), error.code, error.status, error.permanent) == (
        type(catalogue),
        catalogue.code,
        catalogue.status,
        catalogue.permanent,
    )
    if answer == _UNREACHABLE:
        assert isinstance(error.__cause__, httpx.ConnectError)


def _listing(client: Any) -> Callable[[frozenset[str]], Any]:
    """The Model catalogue read, shaped like a capability read, for the same Engine answer."""

    return lambda _required: client.models.list()
