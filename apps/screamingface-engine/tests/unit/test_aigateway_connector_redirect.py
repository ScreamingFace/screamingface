"""A fronting proxy or SSO gateway must fail with a NAMED error, not a raw decode crash.

These used to drive the `/v1/models` catalog fetch at world-build time. Endpoints are declared
now and that fetch is gone, so the same interception is exercised where it can still happen:
the completion call.
"""

import httpx
import pytest

from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run

_TOKEN = "tok"  # noqa: S105 - not a real credential
_MODEL = "claude-haiku-4-5"
_CFG = AigatewayConfig(base_url="http://aigw", default_model=_MODEL, models=(ModelSpec(id=_MODEL),))


def _redirect_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        302,
        headers={"location": "https://sso.example.com/login"},
        text="<html><head><title>302 Found</title></head><body></body></html>",
    )


def _html_200_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})


async def _error_from(handler) -> ResolutionError:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://aigw")
    async with client:
        world = await build_aigateway_world(_CFG, client=client)
        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)
    return exc_info.value


@pytest.mark.asyncio
async def test_a_redirect_from_a_fronting_proxy_raises_a_named_error() -> None:
    error = await _error_from(_redirect_handler)

    assert error.code == "aigateway_bad_response"
    assert error.permanent is True
    assert "302" in str(error)


@pytest.mark.asyncio
async def test_a_non_json_success_body_raises_a_named_error() -> None:
    error = await _error_from(_html_200_handler)

    assert error.code == "aigateway_bad_response"
    assert error.permanent is True
