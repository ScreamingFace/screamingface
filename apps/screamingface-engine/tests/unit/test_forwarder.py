"""u3-forwarder — the App's verbatim forward to the node tier (prd/03 §2.2, contracts.md C2).

# WHY these tests come in this order. The forwarder is the one hop the public caller never sees,
# and it is where two risks meet: impersonation (a forged ``X-User-Email`` must never leave) and
# retry amplification (a timeout may be mid-call and billable, so it must not be retried). T2 is
# written first, then the route-agreement set (T10), then the ladder (T7) and the retry policy
# (T8). The stub node records every outbound request, so "was it forwarded?" is an assertion about
# a fact, not about a status code.

Stubbed node throughout: no real external API is called, so the suite runs offline.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.datastructures import Headers

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.forwarder import (
    NodeForwarder,
    derive_forward_contract,
    forwarded_headers,
)

_MODEL = "anthropic/claude-haiku-4-5"
_MOUNTS = frozenset({f"/{_MODEL}", "/corpus/papers"})
_VERIFIED = "verified@example.com"
_FORGED = "forged@example.com"

pytestmark = pytest.mark.asyncio

# The repo's own declared world; the forwarder derives its mount set from exactly this file.
_REPO_CONFIG = Path(__file__).resolve().parents[2] / "url4.toml"

Behavior = Callable[[httpx.Request], httpx.Response]


def _ok(
    status: int = 200, body: bytes = b"ok", headers: Mapping[str, str] | None = None
) -> Behavior:
    return lambda _request: httpx.Response(status, content=body, headers=dict(headers or {}))


def _raises(exc: Exception) -> Behavior:
    def behavior(_request: httpx.Request) -> httpx.Response:
        raise exc

    return behavior


class _StubNode:
    """A canned node that records every request it receives.

    WHY not ``respx``: the transport IS the assertion surface here (which headers left, how many
    attempts), and one in-process recorder keeps both visible without a global patch.
    """

    def __init__(self, *behaviors: Behavior) -> None:
        self.calls: list[httpx.Request] = []
        self._behaviors = behaviors or (_ok(),)

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            behavior = self._behaviors[min(len(self.calls) - 1, len(self._behaviors) - 1)]
            return behavior(request)

        return httpx.MockTransport(handler)


def _forwarder(
    stub: _StubNode,
    *,
    mounts: frozenset[str] = _MOUNTS,
    identity_resolver: Callable[[Headers], Mapping[str, str]] | None = None,
    **kwargs: object,
) -> NodeForwarder:
    return NodeForwarder(
        node_base_url="http://node.test",
        mount_paths=mounts,
        identity_resolver=identity_resolver,
        client=httpx.AsyncClient(transport=stub.transport()),
        **kwargs,  # type: ignore[arg-type]
    )


def _app(forwarder: NodeForwarder) -> FastAPI:
    return create_app(Settings(jwt_secret="s" * 32), forwarder=forwarder)


def _app_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test")


# --- T2 / AC4: the verified identity is the only identity that leaves -------------------------


async def test_forwarded_headers_strip_the_client_identity_and_set_the_verified_one() -> None:
    """The shared strip-and-reset helper: no inbound identity survives, the verified one is set."""
    inbound = [
        ("X-User-Email", _FORGED),
        ("Cookie", "session=secret"),
        ("Authorization", "Bearer secret"),
        ("URL4-Capability", "jwt"),
        ("X-Profile", "team-a"),
        ("Cache-Control", "no-store"),
        ("X-Answer-Seed", "7"),
        ("traceparent", "00-" + "a" * 32 + "-" + "b" * 16 + "-01"),
    ]

    out = forwarded_headers(inbound, verified_identity={"X-User-Email": _VERIFIED})

    assert ("X-User-Email", _VERIFIED) in out
    assert ("X-User-Email", _FORGED) not in out
    assert [name for name, _ in out if name.lower() == "x-user-email"] == ["X-User-Email"]
    assert ("X-Profile", "team-a") in out
    assert ("Cache-Control", "no-store") in out
    assert ("X-Answer-Seed", "7") in out
    assert any(name.lower() == "traceparent" for name, _ in out)
    assert not any(
        name.lower() in {"cookie", "authorization", "url4-capability"} for name, _ in out
    )


async def test_a_forged_identity_header_is_replaced_by_the_verified_value() -> None:
    """AC4: the outbound request carries the edge-verified value, never the client's."""
    stub = _StubNode(_ok(body=b"PARIS"))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(
            f"/{_MODEL}",
            params={"q": "('')!'Reply with exactly: PARIS'"},
            headers={"X-User-Email": _FORGED, "Cookie": "session=secret"},
        )

    assert response.status_code == 200
    assert len(stub.calls) == 1
    sent = stub.calls[0]
    assert sent.headers.get("X-User-Email") == _VERIFIED
    assert sent.headers.get("X-User-Email") != _FORGED
    assert "cookie" not in sent.headers


async def test_a_request_without_verified_identity_is_rejected_and_not_forwarded() -> None:
    """AC4: no verified identity is a 403, never an anonymous forward."""
    stub = _StubNode()
    forwarder = _forwarder(stub)  # default resolver reads the edge-injected header
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", params={"q": "('')!'x'"})

    assert response.status_code == 403
    assert json.loads(response.text)["error"]["code"] == "identity_access_denied"
    assert stub.calls == []


async def test_the_forwarded_request_carries_path_and_query_unchanged() -> None:
    """C2: the path and query are forwarded verbatim, including percent-encoding."""
    stub = _StubNode()
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    query = "q=(%27%27)!%27Reply%20with%20PARIS%27"
    async with _app_client(_app(forwarder)) as client:
        await client.get(f"/{_MODEL}?{query}", headers={"X-User-Email": _FORGED})

    sent = stub.calls[0]
    assert sent.url.path == f"/{_MODEL}"
    assert sent.url.query == query.encode()


# --- T10 / AC12: only known mounts are forwarded ----------------------------------------------


async def test_an_unknown_path_404s_at_the_app_without_forwarding() -> None:
    """AC12: a path outside the set is answered at the App and never reaches the node."""
    stub = _StubNode()
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get("/not/a/mount", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 404
    assert json.loads(response.text)["error"]["code"] == "endpoint_not_found"
    assert stub.calls == []


async def test_a_known_mount_is_forwarded() -> None:
    stub = _StubNode(_ok(body=b"rows"))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get("/corpus/papers", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 200
    assert response.text == "rows"
    assert len(stub.calls) == 1


# --- T8 / AC9: retry only what is safe --------------------------------------------------------


async def test_a_connection_error_is_retried_exactly_once() -> None:
    refused = httpx.ConnectError(
        "connection refused", request=httpx.Request("GET", "http://node.test")
    )
    stub = _StubNode(_raises(refused), _ok(body=b"PARIS"))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 200
    assert len(stub.calls) == 2


async def test_a_timeout_is_not_retried() -> None:
    timeout = httpx.ReadTimeout("node slow", request=httpx.Request("GET", "http://node.test"))
    stub = _StubNode(_raises(timeout))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert len(stub.calls) == 1
    assert response.status_code == 504


async def test_a_five_hundred_is_not_retried() -> None:
    stub = _StubNode(_ok(status=500, body=b"boom"))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert len(stub.calls) == 1
    assert response.status_code == 500
    assert response.text == "boom"


# --- T7 / AC7, AC8: the pass-through and the node-down floor ----------------------------------


async def test_a_node_503_and_retry_after_pass_through_unmodified() -> None:
    """AC7: the node's own shedding is not rewritten by the forwarder."""
    body = json.dumps({"error": {"code": "overloaded", "message": "capacity"}}).encode()
    stub = _StubNode(_ok(status=503, body=body, headers={"Retry-After": "7"}))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "7"
    assert response.content == body


async def test_node_down_is_503_with_retry_after_and_never_500() -> None:
    """AC8: an unreachable node is a 503 + Retry-After, never a 500."""

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    stub = _StubNode(refused)
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.status_code != 500
    assert len(stub.calls) == 2


async def test_a_303_location_is_rewritten_when_the_prefix_differs_and_keeps_the_query() -> None:
    location = "/artifacts/abc123?exp=1000&sig=deadbeef"
    stub = _StubNode(_ok(status=303, body=b"", headers={"Location": location}))
    forwarder = _forwarder(
        stub,
        identity_resolver=lambda _h: {"X-User-Email": _VERIFIED},
        node_artifact_prefix="/artifacts/",
        app_artifact_prefix="/downloads/",
    )
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert response.status_code == 303
    assert response.headers["Location"] == "/downloads/abc123?exp=1000&sig=deadbeef"


async def test_a_303_location_is_unchanged_when_the_prefixes_match() -> None:
    location = "/artifacts/abc123?exp=1000&sig=deadbeef"
    stub = _StubNode(_ok(status=303, body=b"", headers={"Location": location}))
    forwarder = _forwarder(stub, identity_resolver=lambda _h: {"X-User-Email": _VERIFIED})
    async with _app_client(_app(forwarder)) as client:
        response = await client.get(f"/{_MODEL}", headers={"X-User-Email": _VERIFIED})

    assert response.headers["Location"] == location


# --- config_digest on health ------------------------------------------------------------------


async def test_healthz_reports_the_config_digest_when_the_forwarder_is_configured() -> None:
    """erd.md §2: a rolling deploy where the two tiers disagree is visible on health."""
    stub = _StubNode()
    forwarder = _forwarder(
        stub,
        identity_resolver=lambda _h: {"X-User-Email": _VERIFIED},
        config_digest="abc123",
    )
    async with _app_client(_app(forwarder)) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "config_digest": "abc123"}


async def test_healthz_has_no_digest_without_a_forwarder() -> None:
    """The existing health contract is unchanged on an App that serves no sync surface."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(Settings(jwt_secret="s" * 32))),
        base_url="http://app.test",
    ) as client:
        response = await client.get("/healthz")

    assert response.json() == {"status": "ok"}


# --- the derived contract: same declaration, both halves --------------------------------------


async def test_derive_forward_contract_reads_mounts_and_digest_from_the_world_file() -> None:
    """The App's mount set comes from the same `world` module the node uses, with no network."""
    contract = await derive_forward_contract(
        env={job_env.RUNNER_CONFIG: str(_REPO_CONFIG)},
        engine_routes=frozenset({"/", "/token", "/v1/models"}),
    )

    assert f"/{_MODEL}" in contract.mount_paths
    expected = hashlib.sha256(_REPO_CONFIG.read_bytes()).hexdigest()
    assert contract.config_digest == expected


async def test_derive_forward_contract_surfaces_a_config_error() -> None:
    """C7: a half-configured node must not start; the App's derivation fails the same way."""
    from screamingface_engine.world.config import WorldConfigError

    with pytest.raises(WorldConfigError):
        await derive_forward_contract(
            env={job_env.RUNNER_CONFIG: "/does/not/exist.toml"},
            engine_routes=frozenset(),
        )
