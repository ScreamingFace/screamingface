"""Boundary tests for POST /v1/chat/completions: media type, identity, body cap, validation.

prd/chat-completion.md CC-1, CC-2, CC-3, CC-4, CC-15, CC-16, CC-24, CC-25, CC-33, CC-34, CC-35 and
CC-42. The App is the real create_app with a scripted runner and an in-memory chat-input store.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

import pytest
from _chat_app import (
    EMAIL,
    MESSAGES,
    PATH,
    ChatApp,
    answered,
    asgi_call,
    asgi_scope,
    body,
    chat_app,
    client,
    error,
    padded,
    post,
    sent_body,
    sent_status,
    stored_bytes,
    stored_record,
)

pytestmark = pytest.mark.asyncio

JSON_TYPE = {"Content-Type": "application/json"}


async def test_hosted_request_without_identity_is_401_and_starts_no_run() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(), headers=JSON_TYPE)
    assert resp.status_code == 401
    assert error(resp)["code"] == "identity_required"
    assert error(resp)["type"] == "invalid_request_error"
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}
    assert ca.source is not None and ca.source.calls == []


async def test_authorization_header_gives_no_identity_and_is_not_forwarded() -> None:
    refused = chat_app(answered())
    resp = await post(
        refused.app, body(), headers={**JSON_TYPE, "Authorization": "Bearer sk-test-123"}
    )
    assert resp.status_code == 401
    assert error(resp)["code"] == "identity_required"
    assert refused.runner.scheduled == []

    ca = chat_app(answered())
    resp = await post(ca.app, body(), headers={**EMAIL, "Authorization": "Bearer sk-test-123"})
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["identity"] == {"X-User-Email": "caller@example.com"}
    assert "sk-test-123" not in repr(ca.runner.scheduled)


async def test_body_over_cap_is_413_before_blob_write() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, padded(body(), 8_000_001))
    assert resp.status_code == 413
    assert error(resp)["code"] == "request_too_large"
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}

    at_cap = chat_app(answered())
    resp = await post(at_cap.app, padded(body(), 8_000_000))
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        (b"not json", None),
        (json.dumps({"model": "prov/a", "messages": []}).encode(), "messages"),
        (json.dumps({"model": 5, "messages": MESSAGES}).encode(), "model"),
    ],
)
async def test_invalid_shape_is_400_with_param_in_openai_envelope(
    payload: bytes, param: str | None
) -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, payload)
    assert resp.status_code == 400
    assert error(resp)["code"] == "invalid_request"
    assert error(resp)["param"] == param
    assert error(resp)["type"] == "invalid_request_error"
    assert set(resp.json()) == {"error"}
    assert set(error(resp)) == {"message", "type", "param", "code"}
    assert resp.headers["content-type"].startswith("application/json")
    assert ca.runner.scheduled == []


async def test_sampling_fields_are_accepted_and_not_stored_in_chat_input() -> None:
    ca = chat_app(answered())
    sampling = {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 5,
        "max_completion_tokens": 5,
        "stop": ["x"],
        "seed": 7,
        "response_format": {"type": "text"},
        "reasoning_effort": "low",
        "presence_penalty": 0.1,
        "frequency_penalty": 0.1,
    }
    resp = await post(ca.app, body(**sampling))
    assert resp.status_code == 200
    record = stored_record(ca.runner.inputs[0])
    assert set(record) == {"schema", "messages"}
    assert record["messages"] == MESSAGES
    raw = stored_bytes(ca.runner.inputs[0])
    for name in sampling:
        assert name.encode() not in raw


@pytest.mark.parametrize(
    ("extra", "param"),
    [
        ({"n": 2}, "n"),
        ({"logprobs": True}, "logprobs"),
        ({"modalities": ["text", "audio"]}, "modalities"),
        ({"audio": {"voice": "alloy", "format": "wav"}}, "audio"),
    ],
)
async def test_n_above_one_and_logprobs_are_400_unsupported_parameter(
    extra: dict[str, Any], param: str
) -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(**extra))
    assert resp.status_code == 400
    assert error(resp)["code"] == "unsupported_parameter"
    assert error(resp)["param"] == param
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.scheduled == []


async def test_n_of_one_is_accepted() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(n=1))
    assert resp.status_code == 200


async def test_unknown_client_fields_are_accepted_and_ignored() -> None:
    ca = chat_app(answered())
    extra = {
        "store": True,
        "metadata": {"k": "v"},
        "user": "u-1",
        "prompt_cache_key": "pk",
        "parallel_tool_calls": False,
        "stream_options": {"include_usage": True},
    }
    resp = await post(ca.app, body(**extra))
    assert resp.status_code == 200
    assert set(stored_record(ca.runner.inputs[0])) == {"schema", "messages"}


@pytest.mark.parametrize(
    ("content", "param"),
    [
        (
            [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
            ],
            "messages[0].content[1]",
        ),
        (
            [{"type": "file", "file": {"file_data": "https://example.com/a.pdf"}}],
            "messages[0].content[0]",
        ),
    ],
)
async def test_remote_media_url_is_400_unsupported_content(
    content: list[dict[str, Any]], param: str
) -> None:
    ca = chat_app(answered())
    messages = [{"role": "user", "content": content}]
    resp = await post(ca.app, body(messages=messages))
    assert resp.status_code == 400
    assert error(resp)["code"] == "unsupported_content"
    assert error(resp)["param"] == param
    assert ca.runner.scheduled == []


async def test_a_data_uri_picture_is_accepted() -> None:
    ca = chat_app(answered())
    content = [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
    ]
    resp = await post(ca.app, body(messages=[{"role": "user", "content": content}]))
    assert resp.status_code == 200


async def test_model_over_32000_chars_is_413() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(model="(" + "x" * 32_000))
    assert resp.status_code == 413
    assert error(resp)["code"] == "request_too_large"
    assert error(resp)["param"] == "model"
    assert ca.source is not None and ca.source.calls == []

    at_limit = chat_app(answered())
    resp = await post(at_limit.app, body(model="(" + "x" * 31_999))
    assert resp.status_code != 413
    assert error(resp)["code"] == "recipe_invalid"


async def test_non_json_content_type_is_415_before_body_read() -> None:
    ca = chat_app(answered())
    read = [False]

    async def chunks() -> AsyncIterator[bytes]:
        read[0] = True
        yield json.dumps(body()).encode()

    async with client(ca.app) as c:
        resp = await c.post(PATH, content=chunks(), headers={**EMAIL, "Content-Type": "text/plain"})
    assert resp.status_code == 415
    assert error(resp)["code"] == "unsupported_media_type"
    assert error(resp)["type"] == "invalid_request_error"
    assert read[0] is False
    assert ca.runner.scheduled == []


async def test_missing_content_type_and_identity_is_415_before_401() -> None:
    ca = chat_app(answered())
    async with client(ca.app) as c:
        resp = await c.post(PATH, content=json.dumps(body()).encode())
    assert resp.status_code == 415
    assert error(resp)["code"] == "unsupported_media_type"
    assert ca.runner.scheduled == []


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "Application/JSON"])
async def test_content_type_with_charset_parameter_is_accepted(content_type: str) -> None:
    ca = chat_app(answered())
    payload = json.dumps(body()).encode()
    resp = await post(ca.app, payload, headers={**EMAIL, "Content-Type": content_type})
    assert resp.status_code == 200


async def test_a_declared_length_over_cap_is_413_before_any_body_read() -> None:
    """CC-3: the Content-Length check refuses before the route reads one byte."""
    ca = chat_app(answered())

    async def receive() -> dict[str, Any]:
        pytest.fail("the route read the body of a request it must refuse first")

    sent = await asgi_call(ca.app, asgi_scope(8_000_001), receive)
    assert sent_status(sent) == 413
    assert sent_body(sent)["error"]["code"] == "request_too_large"
    assert ca.runner.attempted == []


async def _five_large_parses(ca: ChatApp, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Sends 5 large requests at once while each parse blocks; the statuses, and checks that at
    most 4 parse at one time and that the fifth gets its 429 while the 4 still parse."""
    from screamingface_engine.rest import chat_body

    ca.app.state.chat_parse_gate = chat_body.ParseGate(places=4, wait_s=0.2)
    real = chat_body._checked
    lock, release = threading.Lock(), threading.Event()
    counts = {"now": 0, "most": 0}

    def parse(raw: bytes) -> Any:
        with lock:
            counts["now"] += 1
            counts["most"] = max(counts["most"], counts["now"])
        release.wait(5)
        with lock:
            counts["now"] -= 1
        return real(raw)

    monkeypatch.setattr(chat_body, "_checked", parse)
    payload = padded(body(), 1_200_000)
    calls = [asyncio.ensure_future(post(ca.app, payload)) for _ in range(5)]
    try:
        done, _ = await asyncio.wait(calls, timeout=3.0, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1
        assert done.pop().result().status_code == 429
        assert counts["now"] == 4
    finally:
        release.set()
    responses = await asyncio.gather(*calls)
    assert counts["most"] == 4
    return sorted(resp.status_code for resp in responses)


async def test_body_read_stops_at_cap_and_large_parses_are_limited_to_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-35: the running cap, and at most 4 large bodies in the parse phase at one time."""
    assert await _five_large_parses(chat_app(answered()), monkeypatch) == [200, 200, 200, 200, 429]

    ca = chat_app(answered())
    yielded = [0]

    async def chunks() -> AsyncIterator[bytes]:
        yield b"{"
        for _ in range(20):
            yielded[0] += 1
            yield b" " * 1_000_000

    async with client(ca.app) as c:
        resp = await c.post(
            PATH, content=chunks(), headers={**EMAIL, "Content-Type": "application/json"}
        )
    assert resp.status_code == 413
    assert error(resp)["code"] == "request_too_large"
    assert yielded[0] <= 10


async def test_a_large_body_waits_for_one_of_the_parse_places() -> None:
    from screamingface_engine.rest.chat_body import ParseGate

    ca = chat_app(answered())
    assert isinstance(ca.app.state.chat_parse_gate, ParseGate)
    gate = ParseGate(places=4, wait_s=0.05)
    ca.app.state.chat_parse_gate = gate
    for _ in range(4):
        await gate.acquire()

    resp = await post(ca.app, padded(body(), 1_200_000))
    assert resp.status_code == 429
    assert error(resp)["code"] == "overloaded"
    assert error(resp)["type"] == "rate_limit_error"
    assert resp.headers["retry-after"] == "5"
    assert resp.headers["x-should-retry"] == "true"
    assert ca.runner.scheduled == []

    small = await post(ca.app, body())
    assert small.status_code == 200

    gate.release()
    resp = await post(ca.app, padded(body(), 1_200_000))
    assert resp.status_code == 200


async def test_many_small_messages_in_a_large_body_are_kept() -> None:
    ca = chat_app(answered())
    messages = [{"role": "user", "content": "x"}] * 30_000
    resp = await post(ca.app, padded(body(messages=messages), 1_100_000))
    assert resp.status_code == 200
    assert len(stored_record(ca.runner.inputs[0])["messages"]) == 30_000
