"""MI-1: type checkers give the exact result type for each surface and each value of ``stream``.

FEATURE: SDK model inference (contracts C1.1 and C1.2, ans:Q7, D13 to D15, risk R3). One method name
serves client.chat, aclient.chat, recipe.chat and sf.chat. The functions ``_sync_rows``,
``_async_rows`` and ``_awaited_rows`` hold one ``assert_type`` for each row of C1.2 and for the
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

import screamingface as sf
from screamingface.chat_completion import AsyncChatStream, ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.inference import (
    AsyncChat,
    AsyncCompletions,
    Chat,
    Completions,
    InferenceEndpoint,
    RecipeChat,
    RecipeCompletions,
)
from screamingface.recipe import Recipe

PACKAGE = Path(__file__).resolve().parents[1]
_MODEL = "openrouter/a"


def _sync_rows(client: Client, recipe: Recipe, flag: bool) -> None:
    assert_type(client.chat, Chat)
    assert_type(client.chat.completions, Completions)
    assert_type(client.chat.completions.create("hi", model=_MODEL), ChatCompletion)
    assert_type(client.chat.completions.create("hi", model=_MODEL, stream=False), ChatCompletion)
    assert_type(client.chat.completions.create("hi", model=_MODEL, stream=True), ChatStream)
    assert_type(
        client.chat.completions.create("hi", model=_MODEL, stream=flag),
        ChatCompletion | ChatStream,
    )
    assert_type(
        client.chat.completions.create(
            model=_MODEL, messages=[{"role": "user", "content": "hi"}], temperature=0.2
        ),
        ChatCompletion,
    )
    assert_type(client.chat.endpoint(_MODEL), InferenceEndpoint)
    assert_type(recipe.chat, RecipeChat)
    assert_type(recipe.chat.completions, RecipeCompletions)
    assert_type(recipe.chat.completions.create("hi"), ChatCompletion)
    assert_type(recipe.chat.completions.create("hi", stream=True), ChatStream)
    assert_type(recipe.chat.completions.create("hi", stream=flag), ChatCompletion | ChatStream)
    assert_type(recipe.chat.endpoint(), InferenceEndpoint)
    assert_type(sf.chat.completions.create("hi", model=_MODEL), ChatCompletion)
    assert_type(sf.chat.completions.create("hi", model=recipe, stream=True), ChatStream)
    assert_type(
        sf.chat.completions.create("hi", model=_MODEL, stream=flag),
        ChatCompletion | ChatStream,
    )
    assert_type(sf.chat.endpoint(_MODEL), InferenceEndpoint)


def _async_rows(client: AsyncClient, flag: bool) -> None:
    assert_type(client.chat, AsyncChat)
    assert_type(client.chat.completions, AsyncCompletions)
    # WHY .close(): pyright reports a coroutine that nothing uses; the close uses it.
    assert_type(
        client.chat.completions.create("hi", model=_MODEL), Coroutine[Any, Any, ChatCompletion]
    ).close()
    assert_type(
        client.chat.completions.create("hi", model=_MODEL, stream=False),
        Coroutine[Any, Any, ChatCompletion],
    ).close()
    assert_type(
        client.chat.completions.create("hi", model=_MODEL, stream=True),
        Coroutine[Any, Any, AsyncChatStream],
    ).close()
    assert_type(
        client.chat.completions.create("hi", model=_MODEL, stream=flag),
        Coroutine[Any, Any, ChatCompletion | AsyncChatStream],
    ).close()
    assert_type(client.chat.endpoint(_MODEL), Coroutine[Any, Any, InferenceEndpoint]).close()


async def _awaited_rows(client: AsyncClient, flag: bool) -> None:
    assert_type(await client.chat.completions.create("hi", model=_MODEL), ChatCompletion)
    assert_type(
        await client.chat.completions.create("hi", model=_MODEL, stream=True), AsyncChatStream
    )
    assert_type(
        await client.chat.completions.create("hi", model=_MODEL, stream=flag),
        ChatCompletion | AsyncChatStream,
    )
    # INVARIANT: the async result is a Coroutine, so asyncio.create_task accepts it (MI-24).
    task = asyncio.create_task(client.chat.completions.create("hi", model=_MODEL))
    assert_type(await task, ChatCompletion)
    assert_type(await client.chat.endpoint(_MODEL), InferenceEndpoint)


_SNIPPET_HEAD = """from __future__ import annotations

from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.recipe import Recipe

"""

# WHY sorted: one snippet can break two rules, and pyright does not report them in a fixed order.
REFUSED = {
    "await-a-sync-reply": (
        "async def call(client: Client) -> None:\n"
        "    await client.chat.completions.create('hi', model='m')\n",
        ["reportGeneralTypeIssues"],
    ),
    "an-async-reply-is-a-coroutine": (
        "def call(client: AsyncClient) -> None:\n"
        "    reply: ChatCompletion = client.chat.completions.create('hi', model='m')\n",
        ["reportAssignmentType"],
    ),
    "the-default-sync-reply-is-not-a-stream": (
        "def call(client: Client) -> None:\n"
        "    reply: ChatStream = client.chat.completions.create('hi', model='m')\n",
        ["reportAssignmentType"],
    ),
    "model-is-required": (
        "def call(client: Client) -> None:\n    client.chat.completions.create('hi')\n",
        ["reportCallIssue"],
    ),
    "a-recipe-call-is-sync": (
        "async def call(recipe: Recipe) -> None:\n    await recipe.chat.completions.create('hi')\n",
        ["reportGeneralTypeIssues"],
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


def test_client_chat_keeps_its_client_and_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    with Client(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=_counting_engine(requests),
        save_results=False,
    ) as client:
        assert isinstance(client.chat, Chat)
        assert client.chat is client.chat
        assert client.chat._client is client
        assert client.chat.completions._client is client
        assert isinstance(sf.Model(_MODEL).chat, RecipeChat)

    assert requests == []


@pytest.mark.asyncio
async def test_async_client_chat_keeps_its_client_and_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    async with AsyncClient(
        engine_url="http://engine.test",
        scoreboard_url="http://scoreboard.test",
        http_transport=_counting_engine(requests),
        save_results=False,
    ) as client:
        assert isinstance(client.chat, AsyncChat)
        assert client.chat._client is client
        assert client.chat.completions._client is client

    assert requests == []
