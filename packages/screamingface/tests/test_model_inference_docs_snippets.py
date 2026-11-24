"""Each Python example of the chat docs runs against the mock Engine (U8, U9, risk R6).

FEATURE: SDK model inference, unit U8 (spec 00-overview P12). public-docs has no test runner, so
this SDK test runs each file of public-docs/src/snippets/chat/ as the docs pages show
it. The mock Engine of tests/_chat_engine.py answers, so no request leaves the machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from _chat_engine import (
    CHAT_PATH,
    ENGINE_URL,
    Handler,
    catalogue_engine,
    recording_client,
    sent_body,
)
from _chat_frames import TOOL_CALL, engine_stream, plain_reply
from _chat_stream import async_recording_client, engine_for
from _endpoint_access import TOKEN_HEADER, hosted_client, signed_in

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.candidate import compile_candidate
from screamingface.warnings import IgnoredParameterWarning

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "public-docs"
SNIPPETS = DOCS / "src" / "snippets" / "chat"
# WHY: the Engine image and some CI checkouts hold only the app; in the monorepo the directory
# exists, so a moved snippet fails loudly instead of skipping.
pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="public-docs is not in this checkout")
RUN = (
    "plain_call.py",
    "openai_form.py",
    "model_per_call.py",
    "stream.py",
    "async_call.py",
    "endpoint_openai.py",
    "candidate_url4.py",
    "openai_one_line.py",
)
TEXT = engine_stream({"role": "assistant", "content": "Hello"}, "stop")
TOOL = engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,))
QUESTION = "What is the capital of France?"


def _engine(payloads: list[dict[str, Any]]) -> Handler:
    answer = engine_for(payloads)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/operators":
            return catalogue_engine(request)
        return answer(request)

    return respond


def _run(name: str) -> dict[str, Any]:
    """Run one snippet file as a script and return its global names."""

    path = SNIPPETS / name
    namespace: dict[str, Any] = {"__name__": "__main__"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def _use(monkeypatch: pytest.MonkeyPatch, client: sf.Client) -> None:
    # WHY: screamingface._inference.calls calls _default_client.default_client() at each call,
    # so a patch here reaches the snippet without a global client.
    monkeypatch.setattr(_default_client, "default_client", lambda: client)


def _chat(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in requests if request.url.path == CHAT_PATH]


def test_each_snippet_file_is_run_here() -> None:
    assert sorted(path.name for path in SNIPPETS.glob("*.py")) == sorted(RUN)


def test_no_snippet_has_an_old_name() -> None:
    for name in RUN:
        text = (SNIPPETS / name).read_text(encoding="utf-8")
        assert "ModelInference" not in text
        assert "chat.complete(" not in text
        assert "InferenceClient" not in text


def test_plain_call(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    requests: list[httpx.Request] = []
    with recording_client(_engine(TEXT), requests) as client:
        _use(monkeypatch, client)
        ns = _run("plain_call.py")

    assert capsys.readouterr().out.splitlines() == ["Hello", "Hello", "5", "0.0012 answered"]
    chat = _chat(requests)
    assert len(chat) == 1
    assert sent_body(chat[0])["model"] == compile_candidate(ns["ensemble"]).url4
    assert sent_body(chat[0])["messages"] == [{"role": "user", "content": QUESTION}]


def test_openai_form(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    requests: list[httpx.Request] = []
    models = ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]
    with recording_client(_engine(TEXT), requests) as client:
        # WHY: the client is built before sf.Client is patched. recording_client calls sf.Client
        # itself, so a patched lambda that called it would recurse.
        monkeypatch.setattr(sf, "Client", lambda *args, **kwargs: client)
        _run("openai_form.py")

    assert capsys.readouterr().out.splitlines() == [f"{model} Hello" for model in models]
    chat = _chat(requests)
    assert [sent_body(request)["model"] for request in chat] == models
    assert all(
        sent_body(request)["messages"] == [{"role": "user", "content": QUESTION}]
        for request in chat
    )


def test_model_per_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    models = ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]
    with recording_client(_engine(TEXT), requests) as client:
        _use(monkeypatch, client)
        _run("model_per_call.py")

    assert capsys.readouterr().out.splitlines() == [f"{model} Hello" for model in models]
    assert [sent_body(request)["model"] for request in _chat(requests)] == models


def test_stream(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    requests: list[httpx.Request] = []
    with recording_client(_engine(TEXT), requests) as client:
        _use(monkeypatch, client)
        _run("stream.py")

    assert capsys.readouterr().out == "Hello\n5\n"
    assert sent_body(_chat(requests)[0])["stream_options"] == {"include_usage": True}


def test_async_call(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    requests: list[httpx.Request] = []
    # WHY: the client is built before sf.AsyncClient is patched. async_recording_client calls
    # sf.AsyncClient itself, so a patched lambda that called it would recurse.
    client = async_recording_client(_engine(TEXT), requests)
    monkeypatch.setattr(sf, "AsyncClient", lambda *args, **kwargs: client)
    _run("async_call.py")

    assert capsys.readouterr().out == "Hello\nHello\n"
    assert len(_chat(requests)) == 2


def _openai_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[httpx.Request]]:
    """Patch openai.OpenAI so that its clients answer from a mock transport.

    The first list collects the keyword arguments of each client; the second, its requests.
    """

    seen: list[dict[str, Any]] = []
    openai_requests: list[httpx.Request] = []
    real = openai.OpenAI

    def plain(request: httpx.Request) -> httpx.Response:
        openai_requests.append(request)
        return httpx.Response(200, json=plain_reply("Hello"))

    def in_process(**kwargs: Any) -> openai.OpenAI:
        seen.append(dict(kwargs))
        transport = httpx.MockTransport(plain)
        return real(**kwargs, max_retries=0, http_client=httpx.Client(transport=transport))

    monkeypatch.setattr(openai, "OpenAI", in_process)
    return seen, openai_requests


def test_endpoint_openai(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen, openai_requests = _openai_in_process(monkeypatch)
    sdk_requests: list[httpx.Request] = []
    with recording_client(_engine(TEXT), sdk_requests) as client:
        _use(monkeypatch, client)
        ns = _run("endpoint_openai.py")

    assert capsys.readouterr().out == "Hello\n"
    assert seen[0]["base_url"] == f"{ENGINE_URL}/v1"
    assert len(openai_requests) == 1
    assert str(openai_requests[0].url) == f"{ENGINE_URL}{CHAT_PATH}"
    url4 = compile_candidate(ns["ensemble"]).url4
    assert sent_body(openai_requests[0])["model"] == ns["endpoint"].model == url4
    # WHY: endpoint() sends no chat request; the OpenAI client sends the only one.
    assert _chat(sdk_requests) == []


def test_endpoint_openai_gives_the_access_token_to_the_openai_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = signed_in(monkeypatch)[0]
    seen, openai_requests = _openai_in_process(monkeypatch)
    sdk_requests: list[httpx.Request] = []
    with hosted_client(_engine(TEXT), sdk_requests) as client:
        _use(monkeypatch, client)
        _run("endpoint_openai.py")

    out = capsys.readouterr().out
    assert out == "Hello\n"
    assert seen[0]["default_headers"][TOKEN_HEADER] == token
    assert len(openai_requests) == 1
    # WHY: the token is a credential; the snippet must not print it.
    assert token not in out
    assert _chat(sdk_requests) == []


def test_candidate_url4(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(_engine(TEXT), requests) as client:
        _use(monkeypatch, client)
        ns = _run("candidate_url4.py")

    out = capsys.readouterr().out
    assert out.rstrip("\n") == compile_candidate(ns["recipe"]).url4
    assert out.startswith("(")
    assert _chat(requests) == []


def test_openai_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MI-45 (D18): the snippet makes its client with the OpenAI arguments, and a conversation
    that keeps the reply message runs with no other change."""
    requests: list[httpx.Request] = []
    answer = _engine(TEXT)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer(request)

    real = sf.Client

    def make(**options: Any) -> sf.Client:
        # WHY: the real constructor runs with the options of the snippet; the test adds only the
        # mock Engine.
        return real(
            engine_url=ENGINE_URL,
            scoreboard_url="http://scoreboard.test",
            http_transport=httpx.MockTransport(respond),
            save_results=False,
            **options,
        )

    monkeypatch.setattr(sf, "Client", make)
    with pytest.warns(IgnoredParameterWarning) as record:
        ns = _run("openai_one_line.py")
    ns["client"].close()

    assert capsys.readouterr().out.splitlines() == ["Hello", "Hello", "5"]
    assert sorted(str(item.message).split("'")[1] for item in record) == ["api_key", "temperature"]
    first, second = (sent_body(request) for request in _chat(requests))
    assert first["model"] == second["model"] == "openrouter/openai/gpt-5.5"
    assert "temperature" not in first
    assert second["messages"] == [
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "And of Italy?"},
    ]
    assert all("sk-..." not in str(request.headers) for request in requests)


def test_no_snippet_declares_a_tool() -> None:
    """MI-50 (D26): tool calls are turned off, so no docs example of the chat calls uses one."""
    for name in RUN:
        text = (SNIPPETS / name).read_text(encoding="utf-8")
        assert "tools" not in text, name
        assert "tool_calls" not in text, name
