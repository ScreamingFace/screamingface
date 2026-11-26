"""MI-2 and MI-3: the streamed chat POST seam of the clients, and when it is sent again (P15).

FEATURE: SDK model inference (contracts C2.1 and C2.5, plan decision D4). The seam sends
`POST /v1/chat/completions` with the replay-safe mark.
INVARIANT: the client sends the POST again only after a sign-in challenge of the hosted edge, and
only one time. It never sends it again after a 408, a 429 or a 5xx, because the HTTP client has no
retry layer. So the client never makes a paid run run two times.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

import screamingface as sf
from screamingface._access.auth import _CloudflareAccessAuth
from screamingface._core.wire import _REPLAY_SAFE

_PATH = "/v1/chat/completions"
_BODY = {"model": "openrouter/a", "messages": [{"role": "user", "content": "hi"}], "stream": True}
_HEADERS = {"Accept": "text/event-stream"}
_TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=60.0)
_TOKEN = "token-after-sign-in"
_DONE = b"data: [DONE]\n\n"
_ENGINES = ["http://engine.test", "https://engine.test"]
_RETRY_STATUSES = [408, 429, 500, 503]
_Handler = Callable[[httpx.Request], httpx.Response]


def _recording(
    handler: _Handler, requests: list[httpx.Request], tokens: list[str | None] | None = None
) -> _Handler:
    """``handler``, which also keeps each request and the Access token it had when it arrived.

    WHY the token list: the auth layer sends the same Request object again, so the test reads
    the header when the request arrives, not after the call.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if tokens is not None:
            tokens.append(request.headers.get("Cf-Access-Token"))
        return handler(request)

    return respond


def _client(engine_url: str, handler: _Handler) -> sf.Client:
    return sf.Client(
        engine_url=engine_url,
        scoreboard_url="https://scoreboard.test",
        http_transport=httpx.MockTransport(handler),
        save_results=False,
    )


def _async_client(engine_url: str, handler: _Handler) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url=engine_url,
        scoreboard_url="https://scoreboard.test",
        http_transport=httpx.MockTransport(handler),
        save_results=False,
    )


def _engine_error(status: int) -> _Handler:
    """An Engine answer that says a retry is safe, so only the client rule stops a resend."""

    return lambda _request: httpx.Response(
        status,
        headers={"x-should-retry": "true", "Retry-After": "1"},
        json={"error": {"message": "busy", "type": "server_error", "code": "engine_busy"}},
    )


_AUDIENCE = "a" * 64
# WHY three forms: P15 names 302, 401 and 403. A 302 carries the audience in the kid of its
# Location, so it goes through another branch of _challenge_audience.
_CHALLENGES = {
    "403-aud": (403, {"cf-access-aud": _AUDIENCE}),
    "401-aud": (401, {"cf-access-aud": _AUDIENCE}),
    "302-kid": (
        302,
        {"location": f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"},
    ),
}
_challenge_forms = pytest.mark.parametrize("challenge", list(_CHALLENGES), ids=list(_CHALLENGES))


def _challenge(name: str) -> httpx.Response:
    status, headers = _CHALLENGES[name]
    return httpx.Response(status, headers=headers)


def _stream_answer() -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_DONE)


def _answers(*responses: httpx.Response) -> _Handler:
    queue = iter(responses)
    return lambda _request: next(queue)


@pytest.fixture
def signed_in_after_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Access signs in with no browser and gives ``_TOKEN``."""

    def set_token(_auth: _CloudflareAccessAuth, request: httpx.Request) -> None:
        request.headers["Cf-Access-Token"] = _TOKEN

    monkeypatch.setattr(
        _CloudflareAccessAuth, "_authenticate_after_redirect", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(_CloudflareAccessAuth, "_set_access_token", set_token)


def test_the_seam_sends_one_marked_post_with_the_body_headers_and_limits() -> None:
    requests: list[httpx.Request] = []
    handler = _recording(lambda _request: _stream_answer(), requests)
    with _client("http://engine.test", handler) as client:
        with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.read() == _DONE

    (request,) = requests
    assert (request.method, request.url.path) == ("POST", _PATH)
    assert json.loads(request.content) == _BODY
    assert request.headers["Accept"] == "text/event-stream"
    assert request.extensions[_REPLAY_SAFE] is True
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 60.0,
        "write": 30.0,
        "pool": 30.0,
    }


@pytest.mark.parametrize("engine_url", _ENGINES)
@pytest.mark.parametrize("status", _RETRY_STATUSES)
def test_chat_post_is_not_sent_again_after_408_429_5xx(engine_url: str, status: int) -> None:
    requests: list[httpx.Request] = []
    with _client(engine_url, _recording(_engine_error(status), requests)) as client:
        with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == status

    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_url", _ENGINES)
@pytest.mark.parametrize("status", _RETRY_STATUSES)
async def test_async_chat_post_is_not_sent_again_after_408_429_5xx(
    engine_url: str, status: int
) -> None:
    requests: list[httpx.Request] = []
    handler = _recording(_engine_error(status), requests)
    async with _async_client(engine_url, handler) as client:
        async with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == status

    assert len(requests) == 1


@_challenge_forms
@pytest.mark.usefixtures("signed_in_after_challenge")
def test_chat_post_is_sent_once_more_after_a_sign_in_challenge(challenge: str) -> None:
    requests: list[httpx.Request] = []
    tokens: list[str | None] = []
    handler = _recording(_answers(_challenge(challenge), _stream_answer()), requests, tokens)
    with _client("https://engine.test", handler) as client:
        with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == 200
            assert response.read() == _DONE

    assert len(requests) == 2
    assert tokens == [None, _TOKEN]
    assert [json.loads(request.content) for request in requests] == [_BODY, _BODY]


@_challenge_forms
@pytest.mark.usefixtures("signed_in_after_challenge")
def test_chat_post_is_sent_only_one_more_time_after_a_second_challenge(challenge: str) -> None:
    requests: list[httpx.Request] = []
    challenges = [_challenge(challenge) for _ in range(3)]
    with _client("https://engine.test", _recording(_answers(*challenges), requests)) as client:
        with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == _CHALLENGES[challenge][0]

    assert len(requests) == 2


@pytest.mark.asyncio
@_challenge_forms
@pytest.mark.usefixtures("signed_in_after_challenge")
async def test_async_chat_post_is_sent_only_one_more_time_after_a_second_challenge(
    challenge: str,
) -> None:
    requests: list[httpx.Request] = []
    challenges = [_challenge(challenge) for _ in range(3)]
    handler = _recording(_answers(*challenges), requests)
    async with _async_client("https://engine.test", handler) as client:
        async with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == _CHALLENGES[challenge][0]

    assert len(requests) == 2


@pytest.mark.asyncio
@_challenge_forms
@pytest.mark.usefixtures("signed_in_after_challenge")
async def test_async_chat_post_is_sent_once_more_after_a_sign_in_challenge(challenge: str) -> None:
    requests: list[httpx.Request] = []
    tokens: list[str | None] = []
    handler = _recording(_answers(_challenge(challenge), _stream_answer()), requests, tokens)
    async with _async_client("https://engine.test", handler) as client:
        async with client._engine_post_stream(
            _PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT
        ) as response:
            assert response.status_code == 200
            assert await response.aread() == _DONE

    assert len(requests) == 2
    assert tokens == [None, _TOKEN]


def test_a_closed_client_refuses_the_chat_post_before_a_request() -> None:
    requests: list[httpx.Request] = []
    handler = _recording(lambda _r: _stream_answer(), requests)
    client = _client("http://engine.test", handler)
    client.close()

    with pytest.raises(RuntimeError, match="Client is closed"):
        client._engine_post_stream(_PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT)

    assert requests == []


@pytest.mark.asyncio
async def test_a_closed_async_client_refuses_the_chat_post_before_a_request() -> None:
    requests: list[httpx.Request] = []
    handler = _recording(lambda _r: _stream_answer(), requests)
    client = _async_client("http://engine.test", handler)
    await client.aclose()

    with pytest.raises(RuntimeError, match="AsyncClient is closed"):
        client._engine_post_stream(_PATH, json=_BODY, headers=_HEADERS, timeout=_TIMEOUT)

    assert requests == []
