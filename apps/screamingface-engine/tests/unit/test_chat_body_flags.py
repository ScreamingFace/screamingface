"""ChatBody needs its stream flags at each construction site (review F7)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from screamingface_engine.rest.chat_body import ChatBody


def test_chat_body_needs_the_stream_flags() -> None:
    make = cast(Any, ChatBody)
    with pytest.raises(TypeError):
        make("m", b"{}", size=2, messages=1)


def test_chat_body_needs_the_tools_flag() -> None:
    make = cast(Any, ChatBody)
    with pytest.raises(TypeError):
        make("m", b"{}", size=2, messages=1, stream=False, include_usage=False)


def test_chat_body_keeps_the_given_stream_flags() -> None:
    got = ChatBody("m", b"{}", size=2, messages=1, stream=True, include_usage=True, has_tools=False)
    assert (got.stream, got.include_usage) == (True, True)
