"""The shared parts of one chat call for the sync and the async path (contracts C1.2, C2.1),
unit U5."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from _chat_engine import CATALOG, vote

from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._inference.request import (
    chat_call,
    check_options,
    model_source,
    model_text,
    model_text_async,
)

MESSAGES = [{"role": "user", "content": "hi"}]


def build(*, stream: bool, stream_options: dict[str, Any] | None) -> Mapping[str, Any]:
    call = chat_call(
        "openrouter/a",
        messages=MESSAGES,
        tools=None,
        stream=stream,
        stream_options=stream_options,
        use_cache=False,
        max_retries=2,
        timeout=5.0,
    )
    assert (call.use_cache, call.max_retries, call.timeout) == (False, 2, 5.0)
    return call.body


@pytest.mark.parametrize("stream_options", [None, {"include_usage": False}])
def test_a_reply_call_always_asks_for_usage(stream_options: dict[str, Any] | None) -> None:
    assert build(stream=False, stream_options=stream_options) == {
        "model": "openrouter/a",
        "messages": MESSAGES,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


@pytest.mark.parametrize(
    ("stream_options", "sent"),
    [
        (None, None),
        ({"include_usage": True}, {"include_usage": True}),
        ({"include_usage": False}, {"include_usage": False}),
    ],
)
def test_a_stream_call_sends_the_stream_options_of_the_caller(
    stream_options: dict[str, Any] | None, sent: dict[str, Any] | None
) -> None:
    """C2.1 / P6: the caller of a stream gets the chunks that an OpenAI client gets."""

    body = build(stream=True, stream_options=stream_options)

    assert body.get("stream_options") == sent
    assert body["stream"] is True


def test_chat_call_sends_tools_when_given() -> None:
    tools = [{"type": "function", "function": {"name": "f"}}]

    call = chat_call(
        "m",
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        stream=False,
        stream_options=None,
        use_cache=True,
        max_retries=0,
        timeout=None,
    )

    assert call.body["tools"] == tools


@pytest.mark.parametrize("value", [1, "yes", None])
def test_include_usage_that_is_not_a_bool_is_a_type_error(value: object) -> None:
    with pytest.raises(TypeError, match="include_usage"):
        check_options(
            stream=True,
            stream_options={"include_usage": value},
            use_cache=True,
            max_retries=0,
            timeout=None,
        )


@pytest.mark.asyncio
async def test_model_text_async_sends_a_str_with_no_catalogue_load() -> None:
    loads: list[int] = []

    async def load() -> _OperatorCatalog:
        loads.append(1)
        return CATALOG

    assert await model_text_async("openrouter/a", load) == "openrouter/a"
    assert loads == []


@pytest.mark.asyncio
async def test_model_text_async_compiles_a_reducer_recipe_with_the_loaded_catalogue() -> None:
    loads: list[int] = []

    async def load() -> _OperatorCatalog:
        loads.append(1)
        return CATALOG

    source = model_source(vote())
    assert not isinstance(source, str)

    text = await model_text_async(source, load)

    assert text == model_text(source, lambda: CATALOG)
    assert loads == [1]
