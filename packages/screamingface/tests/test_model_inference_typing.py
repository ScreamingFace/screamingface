"""MI-1: type checkers give the exact result type for each client and each value of ``stream``.

FEATURE: SDK model inference (contracts C1.1 and C1.2, ans:Q7, risk R3). One method name serves
the sync and the async client. The functions ``_sync_rows``, ``_async_rows`` and ``_awaited_rows``
hold one ``assert_type`` for each row of C1.2, for the two constructor forms and for the two
results of ``endpoint()``. Pyright checks them: the gate runs pyright on ``tests/``, and the first
test below runs pyright on this file. The run time never calls them.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, assert_type

import httpx
import pytest

from screamingface.chat_completion import AsyncChatStream, ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.inference import Chat, InferenceEndpoint, ModelInference

PACKAGE = Path(__file__).resolve().parents[1]
_MODEL = "openrouter/a"


def _sync_rows(client: Client, flag: bool) -> None:
    default = ModelInference(_MODEL)
    assert_type(default, ModelInference[Client])
    assert_type(ModelInference(_MODEL, client=client), ModelInference[Client])
    assert_type(default.chat, Chat[Client])
    assert_type(default.chat.complete("hi"), ChatCompletion)
    assert_type(default.chat.complete("hi", stream=False), ChatCompletion)
    assert_type(default.chat.complete("hi", stream=True), ChatStream)
    assert_type(default.chat.complete("hi", stream=flag), ChatCompletion | ChatStream)
    assert_type(
        default.chat.complete(messages=[{"role": "user", "content": "hi"}], temperature=0.2),
        ChatCompletion,
    )
    assert_type(default.endpoint(), InferenceEndpoint)


def _async_rows(client: AsyncClient, flag: bool) -> None:
    model = ModelInference(_MODEL, client=client)
    assert_type(model, ModelInference[AsyncClient])
    assert_type(model.chat, Chat[AsyncClient])
    # WHY .close(): pyright reports a coroutine that nothing uses; the close uses it.
    assert_type(model.chat.complete("hi"), Coroutine[Any, Any, ChatCompletion]).close()
    assert_type(
        model.chat.complete("hi", stream=False), Coroutine[Any, Any, ChatCompletion]
    ).close()
    assert_type(
        model.chat.complete("hi", stream=True), Coroutine[Any, Any, AsyncChatStream]
    ).close()
    assert_type(
        model.chat.complete("hi", stream=flag),
        Coroutine[Any, Any, ChatCompletion | AsyncChatStream],
    ).close()
    assert_type(model.endpoint(), Coroutine[Any, Any, InferenceEndpoint]).close()


async def _awaited_rows(client: AsyncClient, flag: bool) -> None:
    model = ModelInference(_MODEL, client=client)
    assert_type(await model.chat.complete("hi"), ChatCompletion)
    assert_type(await model.chat.complete("hi", stream=True), AsyncChatStream)
    assert_type(await model.chat.complete("hi", stream=flag), ChatCompletion | AsyncChatStream)
    # INVARIANT: the async result is a Coroutine, so asyncio.create_task accepts it (MI-24).
    task = asyncio.create_task(model.chat.complete("hi"))
    assert_type(await task, ChatCompletion)
    assert_type(await model.endpoint(), InferenceEndpoint)


_SNIPPET_HEAD = """from __future__ import annotations

from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.inference import ModelInference

"""

# WHY sorted: one snippet can break two rules (a client of another type), and pyright does not
# report them in a fixed order.
REFUSED = {
    "await-a-sync-reply": (
        "async def call(model: ModelInference[Client]) -> None:\n"
        "    await model.chat.complete('hi')\n",
        ["reportGeneralTypeIssues"],
    ),
    "an-async-reply-is-a-coroutine": (
        "def call(model: ModelInference[AsyncClient]) -> None:\n"
        "    reply: ChatCompletion = model.chat.complete('hi')\n",
        ["reportAssignmentType"],
    ),
    "the-default-sync-reply-is-not-a-stream": (
        "def call(model: ModelInference[Client]) -> None:\n"
        "    reply: ChatStream = model.chat.complete('hi')\n",
        ["reportAssignmentType"],
    ),
    "a-client-of-another-type": (
        "def call() -> None:\n    ModelInference('openrouter/a', client=object())\n",
        ["reportArgumentType", "reportCallIssue"],
    ),
}


def _errors(arguments: list[str]) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    report = json.loads(completed.stdout)
    return [
        diagnostic
        for diagnostic in report["generalDiagnostics"]
        if diagnostic["severity"] == "error"
    ]


def _snippet_errors(tmp_path: Path, source: str) -> list[dict[str, Any]]:
    (tmp_path / "snippet.py").write_text(_SNIPPET_HEAD + source, encoding="utf-8")
    config = {
        "include": ["snippet.py"],
        "venvPath": str(PACKAGE),
        "venv": ".venv",
        "pythonVersion": "3.12",
        "typeCheckingMode": "basic",
    }
    (tmp_path / "pyrightconfig.json").write_text(json.dumps(config), encoding="utf-8")
    return _errors(["-p", str(tmp_path)])


def test_typed_overloads_give_exact_results_for_each_client_and_stream_value() -> None:
    assert _errors(["-p", str(PACKAGE), str(Path(__file__))]) == []


@pytest.mark.parametrize(("source", "rules"), list(REFUSED.values()), ids=list(REFUSED))
def test_a_call_that_mixes_the_modes_is_a_type_error(
    tmp_path: Path, source: str, rules: list[str]
) -> None:
    errors = _snippet_errors(tmp_path, source)

    assert sorted(str(error["rule"]) for error in errors) == rules


def _counting_engine(requests: list[httpx.Request]) -> httpx.MockTransport:
    def engine(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    return httpx.MockTransport(engine)


def test_the_constructor_keeps_a_sync_client_and_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    with Client(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=_counting_engine(requests),
        save_results=False,
    ) as client:
        default = ModelInference(_MODEL)
        explicit = ModelInference(_MODEL, client=client)

    assert isinstance(explicit.chat, Chat)
    assert explicit._client is client
    # INVARIANT: with no client, the constructor keeps None; each call takes the default client
    # when it runs (MI-9), not when the object is made.
    assert default._client is None
    assert requests == []


@pytest.mark.asyncio
async def test_the_constructor_keeps_an_async_client_and_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    async with AsyncClient(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=_counting_engine(requests),
        save_results=False,
    ) as client:
        model = ModelInference(_MODEL, client=client)

    assert isinstance(model.chat, Chat)
    assert model._client is client
    assert requests == []
