"""Readiness and dispatch hold an endpoint's HTTP 200 to ONE response contract.

# FEATURE: hosted BYOM Unit 0 — readiness publishes a key only after the endpoint answered what
# every later chat call accepts. A response readiness calls VALID must never fail dispatch on a
# different format rule; readiness may be stricter only in its size and time budget.
# INVARIANT: for every response below, readiness is VALID exactly when dispatch succeeds.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from aigateway.core.api_key_validation import ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .fixtures import (
    ALIAS,
    BAD_METADATA_COMPLETIONS,
    BROKEN_ENVELOPES,
    EDGE_COMPLETIONS,
    ENDPOINT_A,
    ERROR_OR_HUGE_COMPLETIONS,
    FINISHED_COMPLETION,
    GOOD_METADATA_COMPLETIONS,
    JSON_TYPE,
    MALFORMED_COMPLETIONS,
    THIN_COMPLETIONS,
    two_endpoint_document,
)

KEY = "sk-byom-contract-0001"


def _as_json(body: dict[str, Any]) -> tuple[str, bytes]:
    return JSON_TYPE, json.dumps(body).encode()


RESPONSES: dict[str, tuple[str, bytes]] = {
    "finished": _as_json(FINISHED_COMPLETION),
    "json-with-charset": (f"{JSON_TYPE}; charset=utf-8", json.dumps(FINISHED_COMPLETION).encode()),
    **{f"thin-{name}": _as_json(body) for name, body in THIN_COMPLETIONS.items()},
    **{f"malformed-{name}": _as_json(body) for name, body in MALFORMED_COMPLETIONS.items()},
    **BROKEN_ENVELOPES,
    **{f"metadata-{name}": _as_json(body) for name, body in GOOD_METADATA_COMPLETIONS.items()},
    **{f"bad-metadata-{n}": _as_json(body) for n, body in BAD_METADATA_COMPLETIONS.items()},
    **{f"refused-{n}": _as_json(body) for n, body in ERROR_OR_HUGE_COMPLETIONS.items()},
    **{f"edge-{n}": _as_json(body) for n, body in EDGE_COMPLETIONS.items()},
}


def _plugin(content_type: str, body: bytes, status: int = 200) -> RemoteEndpointPlugin:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": content_type})

    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))


async def _readiness_accepts(content_type: str, body: bytes, status: int = 200) -> bool:
    plugin = _plugin(content_type, body, status)
    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)
    assert result is not None
    return result.state is ApiKeyValidationState.VALID


async def _dispatch(content_type: str, body: bytes, status: int = 200) -> HTTPException | None:
    request = {"model": f"{ENDPOINT_A}/{ALIAS}", "messages": [], "api_key": KEY}
    try:
        await _plugin(content_type, body, status).chat_completion(request)
    except HTTPException as exc:
        return exc
    return None


async def _dispatch_accepts(content_type: str, body: bytes) -> bool:
    return await _dispatch(content_type, body) is None


def _status_and_code(refusal: HTTPException | None) -> tuple[int, str]:
    assert refusal is not None
    detail: Any = refusal.detail
    return refusal.status_code, detail["code"]


# WHY an explicit verdict per row: equal verdicts alone would also hold if both branches refused
# everything. A broken envelope (wrong media type, NaN, too deep) is refused by BOTH, and so is
# metadata a caller would misread (a non-text finish reason, a token count that is not a count).
ACCEPTED = frozenset(
    {
        "finished",
        "json-with-charset",
        *(f"thin-{n}" for n in THIN_COMPLETIONS),
        *(f"metadata-{n}" for n in GOOD_METADATA_COMPLETIONS),
        *(f"edge-{n}" for n in EDGE_COMPLETIONS),
    }
)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", RESPONSES)
async def test_readiness_accepts_exactly_what_dispatch_accepts(name: str) -> None:
    response = RESPONSES[name]
    accepted = name in ACCEPTED
    assert (await _readiness_accepts(*response), await _dispatch_accepts(*response)) == (
        accepted,
        accepted,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 203, 206])
async def test_a_success_status_other_than_200_is_refused_by_both(status: int) -> None:
    # INVARIANT: the contract is HTTP 200 exactly, in both branches; a completion under another
    # 2xx status must not publish a key, and must not serve a chat that readiness would refuse.
    response = _as_json(FINISHED_COMPLETION)

    refusal = await _dispatch(*response, status=status)

    assert await _readiness_accepts(*response, status=status) is False
    assert _status_and_code(refusal) == (502, "provider_error")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ERROR_OR_HUGE_COMPLETIONS)
async def test_a_refused_completion_is_a_502_that_echoes_nothing(name: str) -> None:
    refusal = await _dispatch(*_as_json(ERROR_OR_HUGE_COMPLETIONS[name]))

    assert _status_and_code(refusal) == (502, "provider_error")
    assert refusal is not None and "failed" not in json.dumps(refusal.detail)
