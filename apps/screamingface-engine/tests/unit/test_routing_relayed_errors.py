"""A Gateway failure after the preflight never speaks in the routed answer's own codes (OME-1822).

FEATURE: BYOM routing pilot (spec 3.5). The routing codes are the Engine's verdicts: the SDK reads
`routing_preflight_unavailable` as "no model ran, asking again is safe", and the mount answers each
routing code with its own status. A classifier or branch call has been sent by the time its answer
comes back, so its failure keeps the Engine's `aigateway_http_<status>` code, whatever code the
Gateway, or a proxy in front of it, writes into the body.

STORY: as a caller whose routed answer failed after the classifier ran, I am never told that
asking again is safe.

INVARIANT: every routing code is reserved against upstream bodies at the one place an upstream
code enters, `connector._raise_for_status`; the preflight's own outcome keeps its code
(`test_routing_preflight.py`).

INVARIANT (review P3): a relayed failure answers the mount status of any Gateway failure, so no
upstream code reads as a refusal of the caller's request once a model may have run. The Engine's
own refusals keep their meaning (`test_routing_endpoint.py`: an ungranted classifier or branch is
an unknown profile). The message and the code follow spec 3.5 and 6.1 C9
(`test_routing_relay_redaction.py`).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    MODELS,
    Gateway,
    call,
    context,
    engine,
    query,
    run_direct,
    write_world,
)

from screamingface_engine.error_text import ENGINE_ERROR_CODES, ENGINE_RESERVED_CODES, ROUTING_CODES
from screamingface_engine.world.gateway_endpoints import ROUTED_CALL_FAILED_MESSAGE
from screamingface_engine.world.routing import ROUTING_STATUS
from screamingface_engine.world.serving import _ENGINE_STATUS, mount_http_status
from url4.core.errors import ErrorCode

pytestmark = pytest.mark.no_default_scope

_SITES = {
    "classifier": ((CLASSIFICATIONS_PATH, CLASSIFIER), 1, 0),
    "branch": ((CHAT_PATH, MODELS["code"]), 1, 1),
}
"""Where the failure is answered, and the classifier and chat POSTs sent by then."""


def _relayed(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": {"code": code, "message": "after-send failure"}})


def test_every_routing_code_is_reserved_against_an_upstream() -> None:
    assert frozenset(ROUTING_STATUS) <= ENGINE_RESERVED_CODES


def test_the_reserved_routing_codes_are_exactly_the_routing_table() -> None:
    """WHY both ways: a code dropped from the table must not stay reserved without a raiser."""
    assert frozenset(ROUTING_STATUS) == ROUTING_CODES
    # INVARIANT: reserving a routing code vouches for no message (`rest/routes.py` reads
    # `ENGINE_ERROR_CODES` for that).
    assert not (ROUTING_CODES & ENGINE_ERROR_CODES)


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("code", sorted(ROUTING_STATUS))
@pytest.mark.parametrize("status", [400, 429, 502])
async def test_a_routing_code_in_an_upstream_body_keeps_the_engine_code(
    site: str, code: str, status: int
) -> None:
    target, classifications, chats = _SITES[site]
    gateway = Gateway(top="code", script={target: _relayed(status, code)})

    outcome = await run_direct(gateway)

    assert outcome.code() == f"aigateway_http_{status}"
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
async def test_the_app_answers_a_relayed_unavailable_code_as_a_gateway_failure(
    tmp_path: Path, site: str
) -> None:
    """WHY through the App: the mount status and the envelope code are what the SDK reads."""
    target, classifications, chats = _SITES[site]
    gateway = Gateway(top="code", script={target: _relayed(502, "routing_preflight_unavailable")})
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))

    assert (resp.status_code, resp.json()["error"]["code"]) == (502, "aigateway_http_502")
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats


# --- a relayed code with a status of its own (review P3) -----------------------------------------

_SPOKEN_CODES = sorted(set(_ENGINE_STATUS) | {code.value for code in ErrorCode})
"""Every code the mount gives a meaning to: the Engine's status table and url4's vocabulary."""


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("code", _SPOKEN_CODES)
async def test_a_relayed_failure_answers_as_a_gateway_failure_whatever_its_code(
    site: str, code: str
) -> None:
    target, classifications, chats = _SITES[site]
    gateway = Gateway(top="code", script={target: _relayed(502, code)})

    outcome = await run_direct(gateway)

    assert mount_http_status(outcome.code(), permanent=outcome.permanent()) == 502
    assert outcome.code() in {code, "aigateway_http_502"}
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize(
    "code",
    ["classifier_not_found", "malformed_source", "identity_access_denied", "endpoint_not_found"],
)
async def test_a_relayed_refusal_code_becomes_the_gateway_failure_code(
    site: str, code: str
) -> None:
    """WHY these four: a `404`, a `400` and a `403` refusal, and the branch-hiding code."""
    target, _, _ = _SITES[site]
    gateway = Gateway(top="code", script={target: _relayed(502, code)})

    outcome = await run_direct(gateway)

    assert (outcome.code(), outcome.permanent()) == ("aigateway_http_502", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("code", ["classifier_not_found", "malformed_source"])
async def test_the_app_answers_a_relayed_refusal_code_as_a_gateway_failure(
    tmp_path: Path, site: str, code: str
) -> None:
    target, classifications, chats = _SITES[site]
    gateway = Gateway(top="code", script={target: _relayed(502, code)})
    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))

    assert (resp.status_code, resp.json()["error"]["code"]) == (502, "aigateway_http_502")
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats
