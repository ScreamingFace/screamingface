"""Shared fakes for the F-B3 frozen-copy tests: a scripted AI Gateway and a recording Tavily.

FEATURE: OME-1307 — the gateway half (F-B1) is built on another branch, so the tests code against
the design contract (`02-frozen-copy-design.md` §4) and fake it with `httpx.MockTransport`.
Not a test module itself, so the append-only gate sees only new files.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from screamingface_engine.capture_outcomes import CaptureTally, capture_outcomes
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run

MODEL = "anthropic/claude-haiku-4-5"
COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"
TAVILY_KEY = "tvly-test-key"  # noqa: S105 - not a real credential
CHAT = "/v1/chat/completions"
REPLAY_CHAT = f"/v1/frozen-copies/{COPY}/chat/completions"
TOOL_RESULTS = f"/v1/frozen-copies/{COPY}/tool-results"
TOOL_LOOKUP = f"/v1/frozen-copies/{COPY}/tool-results/lookup"
OPEN = "/v1/frozen-copies"
SEAL = f"/v1/frozen-copies/{COPY}/seal"
TAVILY_CACHE_PREFIX = "/v1/retrieval/tavily/cache"
EXPRESSION = f"/{MODEL}(ctx)!go"


def chat(
    content: str = "an answer",
    headers: Mapping[str, str] | None = None,
    *,
    aigw: dict[str, Any] | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    if aigw is not None:
        body["_aigw"] = aigw
    return httpx.Response(200, headers=dict(headers or {}), json=body)


def tool_call(
    name: str,
    arguments: dict[str, Any],
    headers: Mapping[str, str] | None = None,
    *,
    call_id: str = "call_1",
) -> httpx.Response:
    call = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return httpx.Response(
        200,
        headers=dict(headers or {}),
        json={
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def stored() -> dict[str, str]:
    return {"X-AIGW-Capture": "stored"}


def error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": {"code": code, "message": "m"}})


class Gateway:
    """A scripted AI Gateway: chat answers in order, and the frozen-copy routes of §4.3.

    Every request is recorded in ``requests`` as ``(method, path, headers, json body)``.
    """

    def __init__(
        self,
        chat_steps: list[httpx.Response | BaseException] | None = None,
        *,
        replay_steps: list[httpx.Response | BaseException] | None = None,
        open_response: httpx.Response | BaseException | None = None,
        seal_response: httpx.Response | BaseException | None = None,
        tool_store: Callable[[httpx.Request], httpx.Response] | None = None,
        tool_lookup: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self._chat = chat_steps or [chat()]
        self._replay = replay_steps or [chat()]
        self._open = open_response or httpx.Response(201, json={"id": COPY, "status": "open"})
        self._seal = seal_response or httpx.Response(
            200, json={"id": COPY, "status": "sealed", "entries": 1}
        )
        self._tool_store = tool_store or (
            lambda _r: httpx.Response(200, json={"outcome": "stored"})
        )
        self._tool_lookup = tool_lookup or (lambda _r: httpx.Response(404, json={}))
        self.requests: list[tuple[str, str, httpx.Headers, Any]] = []
        self._chat_calls = 0
        self._replay_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, request.headers, body))
        routes: dict[str, Callable[[], httpx.Response]] = {
            CHAT: lambda: self._step(self._chat, "_chat_calls"),
            REPLAY_CHAT: lambda: self._step(self._replay, "_replay_calls"),
            OPEN: lambda: self._respond(self._open),
            SEAL: lambda: self._respond(self._seal),
            TOOL_RESULTS: lambda: self._tool_store(request),
            TOOL_LOOKUP: lambda: self._tool_lookup(request),
        }
        if path.startswith(TAVILY_CACHE_PREFIX):
            return httpx.Response(500)
        if path not in routes:
            raise AssertionError(f"unexpected gateway request {request.method} {path}")
        return routes[path]()

    def _step(self, steps: list[httpx.Response | BaseException], counter: str) -> httpx.Response:
        index = getattr(self, counter)
        setattr(self, counter, index + 1)
        return self._respond(steps[min(index, len(steps) - 1)])

    @staticmethod
    def _respond(step: httpx.Response | BaseException) -> httpx.Response:
        if isinstance(step, BaseException):
            raise step
        return step

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="http://aigateway.test"
        )

    def paths(self) -> list[str]:
        return [path for _method, path, _headers, _body in self.requests]

    def calls(self, path: str) -> list[tuple[httpx.Headers, Any]]:
        return [(h, b) for _m, p, h, b in self.requests if p == path]


class Tavily:
    """A recording Tavily: it answers every call with one search result, or with ``response``."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self._response = response
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response or httpx.Response(
            200, json={"results": [{"title": "T", "url": "https://ok.test/a", "content": "C"}]}
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="https://tavily.test"
        )


def capture_scope(**kwargs: Any) -> RequestScope:
    return RequestScope(origin="run", capture=True, **kwargs)


def replay_scope(**kwargs: Any) -> RequestScope:
    return RequestScope(origin="run", replay_frozen_copy=COPY, **kwargs)


async def run_call(
    gateway: Gateway,
    scope: RequestScope,
    *,
    tavily: Tavily | None = None,
    web_search: bool = True,
    bind_copy: bool = True,
) -> tuple[CaptureTally, str | None, ResolutionError | None]:
    """One model call under ``scope`` with a tally bound, as the executor binds it.

    ``bind_copy`` plays the executor's open step for a capture scope: the tally learns the copy id.
    Returns the tally, the answer text, and the failure (when the call raised).
    """
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL, web_search=web_search),), default_model=MODEL)
    answer: str | None = None
    failure: ResolutionError | None = None
    tavily_client = tavily.client() if tavily is not None else None
    async with gateway.client() as client:
        world = await build_aigateway_world(
            cfg,
            client=client,
            tavily_api_key=TAVILY_KEY if tavily is not None else None,
            tavily_client=tavily_client,
        )
        with request_scope(scope), capture_outcomes() as tally:
            if scope.replay_frozen_copy is not None:
                tally.mode, tally.frozen_copy_id = "replay", scope.replay_frozen_copy
            elif scope.capture:
                tally.mode = "capture"
                if bind_copy:
                    tally.frozen_copy_id = COPY
            try:
                answer = await url4_run(EXPRESSION, io=world.node)
            except ResolutionError as exc:
                failure = exc
    if tavily_client is not None:
        await tavily_client.aclose()
    return tally, answer, failure
