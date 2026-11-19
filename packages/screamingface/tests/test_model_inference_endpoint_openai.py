"""EB-7: the docs example of contracts C5 runs with the real OpenAI client against a mock Engine.

FEATURE: SDK model inference, plan decision D9 (P16). openai==2.54.0 is only a dev dependency.
The SDK does not import openai. The mock Engine answers with the wire of tests/_chat_frames.py,
so the test uses no network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
from _chat_engine import (
    CHAT_PATH,
    ENGINE_URL,
    Handler,
    recording_client,
    reply_body,
    sent_body,
    sse,
)
from _chat_frames import META, USAGE, info, message
from _endpoint_access import HOSTED_URL, TOKEN_HEADER, hosted_client, signed_in

import screamingface as sf
from screamingface.inference import InferenceEndpoint, ModelInference


def _plain_reply(text: str) -> dict[str, Any]:
    """The plain (not streamed) reply of the Engine."""

    return {
        **META,
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message(text), "finish_reason": "stop"}],
        "usage": dict(USAGE),
        "screamingface": info(),
    }


def _engine(requests: list[httpx.Request]) -> Handler:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content).get("stream") is True:
            return sse(reply_body("Hello"))
        return httpx.Response(200, json=_plain_reply("Hello"))

    return respond


def _no_engine_request(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("endpoint() sent an Engine request")


def _endpoint(hosted: bool) -> InferenceEndpoint:
    if hosted:
        with hosted_client(_no_engine_request, []) as client:
            return ModelInference("openrouter/a", client=client).endpoint()
    with recording_client(_no_engine_request, []) as client:
        return ModelInference("openrouter/a", client=client).endpoint()


def _openai_client(e: InferenceEndpoint, requests: list[httpx.Request]) -> openai.OpenAI:
    # WHY max_retries=0: a failed test must not retry with sleeps.
    return openai.OpenAI(
        base_url=e.base_url,
        api_key="unused",
        default_headers=dict(e.headers),
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(_engine(requests))),
    )


@pytest.mark.parametrize("hosted", [False, True], ids=["local", "hosted"])
def test_docs_example_with_the_openai_client_runs(
    hosted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = signed_in(monkeypatch)[0] if hosted else None
    e = _endpoint(hosted)
    requests: list[httpx.Request] = []

    with _openai_client(e, requests) as client:
        reply = client.chat.completions.create(
            model=e.model, messages=[{"role": "user", "content": "Hello"}]
        )

    assert reply.choices[0].message.content == "Hello"
    (request,) = requests
    assert str(request.url) == f"{HOSTED_URL if hosted else ENGINE_URL}{CHAT_PATH}"
    assert request.method == "POST"
    assert sent_body(request)["model"] == "openrouter/a"
    assert request.headers.get(TOKEN_HEADER) == token


@pytest.mark.parametrize("hosted", [False, True], ids=["local", "hosted"])
def test_docs_example_streams_with_the_openai_client(
    hosted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = signed_in(monkeypatch)[0] if hosted else None
    e = _endpoint(hosted)
    requests: list[httpx.Request] = []

    with _openai_client(e, requests) as client:
        stream = client.chat.completions.create(
            model=e.model,
            messages=[{"role": "user", "content": "Hello"}],
            stream=True,
        )
        text = "".join(chunk.choices[0].delta.content or "" for chunk in stream if chunk.choices)

    assert text == "Hello"
    (request,) = requests
    assert sent_body(request)["stream"] is True
    assert request.headers.get(TOKEN_HEADER) == token


def test_docs_example_uses_a_recipe_as_the_model() -> None:
    requests: list[httpx.Request] = []
    recipe = sf.Fanout(["openrouter/a", "openrouter/b"]) >> sf.Synthesize("openrouter/c")

    with recording_client(_no_engine_request, []) as client:
        e = ModelInference(recipe, client=client).endpoint()

    with _openai_client(e, requests) as openai_client:
        openai_client.chat.completions.create(
            model=e.model, messages=[{"role": "user", "content": "Hello"}]
        )

    (request,) = requests
    assert sent_body(request)["model"] == e.model
    assert e.model.lstrip().startswith("(")
