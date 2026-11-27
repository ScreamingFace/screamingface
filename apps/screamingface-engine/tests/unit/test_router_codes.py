"""The Router's Engine codes are reserved: no upstream body can mint one (Unit 5.2, C11).

FEATURE: Router Recipe extension. `router_definition_invalid` and `router_unsupported` (ADMIT) and
`router_evidence_invalid` (DECIDE) say that no model I/O of a Router occurrence ran, or that its
evidence was refused. A branch or classifier failure that could borrow one would claim a refusal
before model I/O after a provider may already have spent.

INVARIANT: `ROUTER_CODES` joins `ENGINE_RESERVED_CODES` and never `ENGINE_ERROR_CODES`; a Gateway
refusal naming one keeps `aigateway_http_<status>`.
"""

from __future__ import annotations

import httpx
import pytest
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    MODELS,
    Gateway,
    run_direct,
)

from screamingface_engine.error_text import (
    ENGINE_ERROR_CODES,
    ENGINE_RESERVED_CODES,
    PUBLIC_UNVOUCHED_CODES,
    ROUTER_CODES,
    ROUTING_CODES,
)
from screamingface_engine.world.gateway_codes import GATEWAY_CODES
from screamingface_engine.world.gateway_transport import _raise_for_status
from screamingface_engine.world.router_spec import DEFINITION_INVALID, ROUTER_UNSUPPORTED
from screamingface_engine.world.routing_policy import ROUTER_EVIDENCE_INVALID
from url4.core.errors import ResolutionError

_ROUTER_CODES = sorted(ROUTER_CODES)


def test_the_router_codes_are_exactly_the_three_the_router_mints() -> None:
    assert ROUTER_CODES == {
        "router_definition_invalid",
        "router_unsupported",
        "router_evidence_invalid",
    }
    assert {DEFINITION_INVALID, ROUTER_UNSUPPORTED, ROUTER_EVIDENCE_INVALID} == ROUTER_CODES


def test_the_router_codes_are_reserved_and_vouch_for_no_message() -> None:
    assert ROUTER_CODES <= ENGINE_RESERVED_CODES
    assert not ROUTER_CODES & ENGINE_ERROR_CODES
    assert not ROUTER_CODES & ROUTING_CODES
    assert not ROUTER_CODES & PUBLIC_UNVOUCHED_CODES
    assert not ROUTER_CODES & GATEWAY_CODES


@pytest.mark.parametrize("code", _ROUTER_CODES)
@pytest.mark.parametrize("status", [400, 409, 422, 502])
def test_a_gateway_refusal_naming_a_router_code_keeps_its_status_code(
    code: str, status: int
) -> None:
    response = httpx.Response(status, json={"detail": {"code": code, "message": "m"}})

    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(response)

    assert caught.value.code == f"aigateway_http_{status}"


@pytest.mark.asyncio
@pytest.mark.no_default_scope
@pytest.mark.parametrize("code", _ROUTER_CODES)
@pytest.mark.parametrize(
    "target",
    [(CLASSIFICATIONS_PATH, CLASSIFIER), (CHAT_PATH, MODELS["code"])],
    ids=["classifier", "branch"],
)
async def test_a_spoofed_router_code_after_a_routed_post_is_the_status_code(
    code: str, target: tuple[str, str]
) -> None:
    gateway = Gateway(top="code")
    gateway.script[target] = httpx.Response(
        422, json={"detail": {"code": code, "message": "no model I/O ran"}}
    )

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_422"
    assert outcome.error is not None
    assert "no model I/O" not in str(outcome.error)
