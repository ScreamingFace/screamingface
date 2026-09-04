"""OME-1026 U2 (§5.2 + plan D1): the OPTIONAL header capability on the discovery envelope.

FEATURE: opt-in live Anthropic model discovery. Anthropic's catalog is credentialed-only
(401 without ``x-api-key``), so a discovery dial must be able to carry static headers —
WITHOUT widening ``DiscoveryHttpClient`` itself, which would break every existing OME-972
test double under pyright, and without changing OpenRouter's credential-free call path.

INVARIANT (legacy compatibility): with no headers, ``fetch_discovery_json`` makes the
byte-identical legacy call — the ``headers`` keyword is not passed at all, so a double
declaring only ``get(url, *, timeout_s, max_bytes)`` keeps working untouched.

INVARIANT (the real runtime guard): ``runtime_checkable`` protocols check method PRESENCE,
never signatures, so ``isinstance`` cannot fail closed on a legacy client. The guarantee is
Python's async argument-binding boundary — the header-carrying coroutine is CREATED inside
``try/except TypeError`` and awaited OUTSIDE it, so a client that cannot bind ``headers``
degrades to ``internal_error`` before its body runs, while a capable client's INTERNAL
``TypeError`` stays distinguishable.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    HeaderCapableDiscoveryClient,
    HttpxDiscoveryClient,
    RawResponse,
    fetch_discovery_json,
)

_ORIGIN = "https://api.anthropic.com"
_URL = "https://api.anthropic.com/v1/models"
_ALLOWED = frozenset({_ORIGIN})
# Obviously-fake material: no real credential ever appears in a fixture.
_FAKE_KEY = "sk-ant-fixture-not-a-real-key"
_HEADERS = {"x-api-key": _FAKE_KEY, "anthropic-version": "2023-06-01"}


def _ok(payload: object) -> RawResponse:
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


class _KwargRecordingClient:
    """Capable double that records EXACTLY which extra kwargs each dial received.

    # WHY ``**extra`` rather than an explicit ``headers=None`` parameter: only this shape
    # can tell "the caller omitted the keyword" from "the caller passed None", which is
    # precisely the legacy-compatibility claim under test.
    """

    def __init__(self) -> None:
        self.extras: list[dict[str, Any]] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int, **extra: Any) -> RawResponse:
        self.extras.append(dict(extra))
        return _ok({"data": []})


class _LegacyClient:
    """An OME-972-era double: no ``headers`` parameter, and a body that must NEVER run."""

    def __init__(self) -> None:
        self.body_executions = 0

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.body_executions += 1
        return _ok({"data": []})


class _InternallyBrokenCapableClient:
    """Capable double whose OWN body raises TypeError once awaited."""

    def __init__(self) -> None:
        self.body_executions = 0

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.body_executions += 1
        raise TypeError("an internal fault inside a capable client, not a binding failure")


@pytest.mark.asyncio
async def test_fetch_discovery_json_forwards_headers_only_when_present() -> None:
    client = _KwargRecordingClient()

    await fetch_discovery_json(_URL, allowed_origins=_ALLOWED, client=client)
    # INVARIANT: the legacy path passes NO headers keyword at all.
    assert client.extras == [{}]

    await fetch_discovery_json(_URL, allowed_origins=_ALLOWED, client=client, headers=_HEADERS)
    # ...and the mapping arrives verbatim when it is supplied.
    assert client.extras[1] == {"headers": _HEADERS}


@pytest.mark.asyncio
async def test_an_explicit_none_headers_argument_keeps_the_legacy_call_path() -> None:
    # WHY pinned separately: ``headers=None`` is the default, so every OpenRouter dial
    # travels this branch. It must stay byte-identical to the pre-OME-1026 call.
    client = _KwargRecordingClient()

    await fetch_discovery_json(_URL, allowed_origins=_ALLOWED, client=client, headers=None)

    assert client.extras == [{}]


@pytest.mark.asyncio
async def test_a_legacy_client_with_headers_fails_closed() -> None:
    client = _LegacyClient()

    with pytest.raises(DiscoveryError) as exc:
        await fetch_discovery_json(_URL, allowed_origins=_ALLOWED, client=client, headers=_HEADERS)

    assert exc.value.reason == "internal_error"
    # INVARIANT: the binding failure is caught at coroutine CREATION, so the client body
    # never ran — a credential-carrying request must never silently become a
    # credential-less dial that a lenient parser could then cache as a fresh catalog.
    assert client.body_executions == 0
    # sanitized: no credential material rides out on the error surface.
    assert _FAKE_KEY not in str(exc.value)
    assert exc.value.status is None


@pytest.mark.asyncio
async def test_a_capable_client_internal_type_error_is_not_a_signature_mismatch() -> None:
    client = _InternallyBrokenCapableClient()

    # INVARIANT: the coroutine is awaited OUTSIDE the binding guard, so a capable client's
    # own TypeError is NOT laundered into DiscoveryError("internal_error") — it escapes to
    # the existing outer sanitization boundary (ModelCatalog), which is what distinguishes
    # "this transport cannot carry headers" from "this transport is broken".
    with pytest.raises(TypeError):
        await fetch_discovery_json(_URL, allowed_origins=_ALLOWED, client=client, headers=_HEADERS)

    assert client.body_executions == 1


@pytest.mark.asyncio
async def test_headers_are_rejected_before_a_non_allowlisted_origin_is_dialed() -> None:
    # INVARIANT (credential hygiene): origin/scheme validation precedes the dial, so a
    # credential can never leave for an unallowlisted host.
    client = _KwargRecordingClient()

    with pytest.raises(DiscoveryError) as exc:
        await fetch_discovery_json(
            "https://evil.example/v1/models",
            allowed_origins=_ALLOWED,
            client=client,
            headers=_HEADERS,
        )

    assert exc.value.reason == "origin_not_allowed"
    assert client.extras == []


@pytest.mark.asyncio
async def test_httpx_discovery_client_attaches_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"data": []}, headers={"content-type": "application/json"})

    client = HttpxDiscoveryClient(transport=httpx.MockTransport(handler))
    response = await client.get(_URL, timeout_s=3.0, max_bytes=1_000_000, headers=_HEADERS)

    assert response.status == 200
    assert seen["x-api-key"] == _FAKE_KEY
    assert seen["anthropic-version"] == "2023-06-01"
    # INVARIANT (CC-14): the adapter's identity encoding is MERGED in and survives, because
    # the bounded read counts wire bytes and only holds while nothing is compressed.
    assert seen["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_identity_encoding_wins_over_a_caller_supplied_encoding_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"data": []}, headers={"content-type": "application/json"})

    client = HttpxDiscoveryClient(transport=httpx.MockTransport(handler))
    await client.get(
        _URL,
        timeout_s=3.0,
        max_bytes=1_000_000,
        headers={"accept-encoding": "gzip", "x-api-key": _FAKE_KEY},
    )

    # INVARIANT: a caller cannot reopen the compression-expansion path the byte cap closes.
    assert seen["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_the_adapter_without_headers_still_sends_only_identity_encoding() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"data": []}, headers={"content-type": "application/json"})

    client = HttpxDiscoveryClient(transport=httpx.MockTransport(handler))
    await client.get(_URL, timeout_s=3.0, max_bytes=1_000_000)

    assert seen["accept-encoding"] == "identity"
    assert "x-api-key" not in seen


@pytest.mark.asyncio
async def test_a_real_transport_dial_with_headers_still_trips_the_no_egress_guard() -> None:
    """CC-1: the shared autouse tripwire must reject, not TypeError, on a header dial.

    # WHY this pin exists: the tripwire wraps ``HttpxDiscoveryClient.get`` with a hardcoded
    # legacy signature. Left unextended, every header-carrying dial through the real adapter
    # would raise TypeError — which ``ModelCatalog`` sanitizes into a degraded seeds listing,
    # so a test that accidentally reached the live internet would pass QUIETLY instead of
    # failing loudly. The guard must stay LOUD for credentialed dials too.
    """
    client = HttpxDiscoveryClient()  # transport=None ⇒ the real, socket-opening path

    with pytest.raises(AssertionError):
        await client.get(_URL, timeout_s=1.0, max_bytes=1_000, headers=_HEADERS)


def test_the_production_adapter_satisfies_both_client_protocols() -> None:
    """The D1 compatibility claim, pinned where a type checker can enforce it.

    # WHY annotated assignments rather than ``isinstance``: a runtime protocol check
    # compares member NAMES only, so it would pass for a legacy client and prove nothing.
    # These two bindings make PYRIGHT verify that the production adapter structurally
    # satisfies the legacy port AND the header capability — the actual invariant, which
    # would go red if the adapter ever lost the optional ``headers`` parameter.
    """
    adapter = HttpxDiscoveryClient()

    legacy: DiscoveryHttpClient = adapter
    capable: HeaderCapableDiscoveryClient = adapter

    assert legacy is adapter and capable is adapter


@pytest.mark.asyncio
async def test_bounds_are_still_enforced_on_a_header_carrying_fetch() -> None:
    # INVARIANT: the credential capability changes WHO may be dialed, never the envelope's
    # bounds — an oversized credentialed response fails exactly like a public one.
    class _BigClient:
        async def get(
            self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
        ) -> RawResponse:
            return _ok({"data": "x" * 5_000})

    with pytest.raises(DiscoveryError) as exc:
        await fetch_discovery_json(
            _URL,
            allowed_origins=_ALLOWED,
            client=_BigClient(),
            limits=DiscoveryLimits(max_bytes=1_000),
            headers=_HEADERS,
        )

    assert exc.value.reason == "oversized"


@pytest.mark.parametrize(
    "spelling", ["Accept-Encoding", "ACCEPT-ENCODING", "aCcEpt-EnCoDiNg", "accept-Encoding"]
)
@pytest.mark.asyncio
async def test_identity_encoding_wins_whatever_case_the_caller_used(spelling: str) -> None:
    """OME-1026 (CC-14): identity wins CASE-INSENSITIVELY, as HTTP field names demand.

    # WHY assert on ``multi_items()`` and not ``dict(request.headers)``: a dict view JOINS
    # duplicate field lines, so ``'gzip, identity'`` would read as containing "identity" and
    # the pin would pass while two Accept-Encoding lines went on the wire — which is exactly
    # the defect this test exists to catch. Only the multi-item view proves there is ONE.
    """
    sent: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.extend(request.headers.multi_items())
        return httpx.Response(200, json={"data": []}, headers={"content-type": "application/json"})

    client = HttpxDiscoveryClient(transport=httpx.MockTransport(handler))
    await client.get(
        _URL,
        timeout_s=3.0,
        max_bytes=1_000_000,
        headers={spelling: "gzip", "x-api-key": _FAKE_KEY},
    )

    # INVARIANT: exactly one accept-encoding line reaches the wire, and it is identity.
    assert [value for name, value in sent if name == "accept-encoding"] == ["identity"]
    # The caller's own (non-encoding) headers still arrive untouched.
    assert [value for name, value in sent if name == "x-api-key"] == [_FAKE_KEY]
