"""MI-41, part 2: timeout and max_retries on the client are the defaults of its chat calls
(overview §5.6, D21; contracts C1.7).

FEATURE: SDK model inference, unit U10.
STORY: as a user of the OpenAI SDK, I keep timeout= and max_retries= on the line that makes my
client, and each chat call of that client uses them.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest
from _chat_engine import ENGINE_URL, answers, envelope, fake_time, ok, reply_body, sse

import screamingface as sf
from screamingface.warnings import IgnoredParameterWarning

KEY = "sk-test-do-not-send-1234567890"
MODEL = "openrouter/a"
BASE_URL = f"{ENGINE_URL}/v1"
RETRY = {"x-should-retry": "true", "Retry-After": "1"}


def _options(handler: Any = ok) -> dict[str, Any]:
    """The test wiring of a SF client: the mock Engine and no results on disk."""

    return {
        "scoreboard_url": "http://scoreboard.test",
        "http_transport": httpx.MockTransport(handler),
        "save_results": False,
    }


def _engine(requests: list[httpx.Request]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return ok(request)

    return respond


def test_client_defaults_apply_to_its_chat_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []

    def retry() -> httpx.Response:
        return envelope(429, "overloaded", headers=RETRY)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    handler = answers(retry(), sse(reply_body()), retry())
    options = _options(respond)
    with sf.Client(engine_url=ENGINE_URL, max_retries=1, timeout=50.0, **options) as client:
        reply = client.chat.completions.create("Hello", model=MODEL)
        assert reply.text == "Hello"
        assert len(requests) == 2
        assert fake.sleeps == [1.0]
        assert requests[0].extensions["timeout"]["read"] == 50.0
        # C1.7: a value on the call replaces the default of the client for that call.
        with pytest.raises(sf.ScreamingFaceError):
            client.chat.completions.create("Hello", model=MODEL, max_retries=0, timeout=20.0)

    assert len(requests) == 3
    assert requests[2].extensions["timeout"]["read"] == 20.0


def test_an_httpx_timeout_gives_its_read_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: the transport sends the time that is left; with the fake clock it is the full limit.
    fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    limits = httpx.Timeout(30.0, connect=5.0)
    with sf.Client(engine_url=ENGINE_URL, timeout=limits, **_options(_engine(requests))) as client:
        client.chat.completions.create("Hello", model=MODEL)
        client.chat.completions.create("Hello", model=MODEL, timeout=httpx.Timeout(12.0))
    with (
        sf.Client(engine_url=ENGINE_URL, **_options(_engine(requests))) as plain,
        sf.Client(
            engine_url=ENGINE_URL, timeout=httpx.Timeout(None), **_options(_engine(requests))
        ) as no_limit,
    ):
        plain.chat.completions.create("Hello", model=MODEL)
        no_limit.chat.completions.create("Hello", model=MODEL)

    assert requests[0].extensions["timeout"]["read"] == 30.0
    assert requests[1].extensions["timeout"]["read"] == 12.0
    # A read value of None is no limit of the SDK, as a client with no timeout.
    assert requests[3].extensions["timeout"] == requests[2].extensions["timeout"]


@pytest.mark.parametrize(
    ("options", "error"),
    [
        ({"timeout": 0}, ValueError),
        ({"timeout": float("inf")}, ValueError),
        ({"timeout": "30"}, TypeError),
        ({"timeout": True}, TypeError),
        ({"max_retries": -1}, ValueError),
        ({"max_retries": 1.5}, TypeError),
        ({"max_retries": None}, TypeError),
        ({"max_retries": True}, TypeError),
    ],
)
@pytest.mark.parametrize("make", [sf.Client, sf.AsyncClient])
def test_client_default_errors(make: Any, options: dict[str, Any], error: type[Exception]) -> None:
    with pytest.raises(error, match=next(iter(options))):
        make(**options, **_options())


@pytest.mark.asyncio
async def test_the_async_client_has_the_same_options(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    options = {**_options(_engine(requests)), "base_url": BASE_URL}
    with pytest.warns(IgnoredParameterWarning) as record:
        expected_line = sys._getframe().f_lineno + 1
        client = sf.AsyncClient(api_key=KEY, timeout=50.0, project="p", **options)
    async with client:
        assert client.engine_url == ENGINE_URL
        assert not hasattr(client, "api_key")
        reply = await client.chat.completions.create("Hello", model=MODEL, max_retries=None)

    assert sorted(str(item.message).split("'")[1] for item in record) == ["api_key", "project"]
    assert all(item.lineno == expected_line and item.filename == __file__ for item in record)
    assert reply.text == "Hello"
    assert requests[0].extensions["timeout"]["read"] == 50.0
    assert all(KEY not in value for value in requests[0].headers.values())
