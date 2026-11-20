"""A follow never starts a sign-in of its own (E5 P2 spec D15; #1878 review round 3).

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose sign-in expires during a long
attached evaluation, the follow ends at once with how to pick the Run up, instead of opening a
browser login, or hanging a headless notebook, in the middle of fetching a result.

INVARIANT: a request marked `_NO_LOGIN` that Cloudflare Access challenges raises
`access_login_not_started`; it adopts a sign-in another request already made, and never presents
a browser login.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from test_authentication import _AUDIENCE

from screamingface._access.auth import _CloudflareAccessAuth
from screamingface._core.wire import _NO_LOGIN, LOGIN_NOT_STARTED
from screamingface.errors import AuthenticationError

_ENGINE = "https://engine.example"
_ROUTE = "/runs/run_" + "a" * 32 + "/candidates/0/result"


def _challenged(request: httpx.Request) -> httpx.Response:
    location = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"
    return httpx.Response(302, headers={"location": location})


def test_a_request_that_may_not_log_in_raises_instead_of_opening_a_browser() -> None:
    browser: list[str] = []
    auth = _CloudflareAccessAuth(_ENGINE, browser_presenter=browser.append)
    with httpx.Client(base_url=_ENGINE, auth=auth, transport=httpx.MockTransport(_challenged)) as h:
        with pytest.raises(AuthenticationError) as raised:
            h.get(_ROUTE, extensions={_NO_LOGIN: True})

    assert raised.value.code == LOGIN_NOT_STARTED
    assert browser == []
    auth.close()


@pytest.mark.asyncio
async def test_an_async_request_that_may_not_log_in_raises_instead_of_opening_a_browser() -> None:
    browser: list[str] = []
    auth = _CloudflareAccessAuth(_ENGINE, browser_presenter=browser.append)
    transport = httpx.MockTransport(_challenged)
    async with httpx.AsyncClient(base_url=_ENGINE, auth=auth, transport=transport) as http:
        with pytest.raises(AuthenticationError) as raised:
            await http.get(_ROUTE, extensions={_NO_LOGIN: True})

    assert raised.value.code == LOGIN_NOT_STARTED
    assert browser == []
    auth.close()


RUN = "run_" + "a" * 32


def test_the_cancel_ctrl_c_sends_never_starts_a_sign_in() -> None:
    """D15: Ctrl-C must not wait on a browser login; a challenged cancel fails, the Run's
    orphan rule stops it, and the interruption the user sees is kept."""
    from screamingface._engine.run_client import RunClient

    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    with httpx.Client(
        base_url="https://engine.example", transport=httpx.MockTransport(answer)
    ) as http:
        RunClient(http, "https://engine.example", cast(Any, object()), None).cancel(RUN)

    assert seen[0].method == "DELETE"
    assert seen[0].extensions.get(_NO_LOGIN) is True


@pytest.mark.asyncio
async def test_the_async_cancel_never_starts_a_sign_in() -> None:
    from screamingface._engine.run_client import AsyncRunClient

    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    transport = httpx.MockTransport(answer)
    async with httpx.AsyncClient(base_url="https://engine.example", transport=transport) as http:
        client = AsyncRunClient(http, "https://engine.example", cast(Any, object()), None)
        await client.cancel(RUN)

    assert seen[0].extensions.get(_NO_LOGIN) is True
