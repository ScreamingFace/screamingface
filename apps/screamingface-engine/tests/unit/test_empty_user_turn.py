"""A call never sends an empty user turn (OME-1808).

A default-route reduce with no attachments has an empty context; its intent holds the members'
answers and the fusion prompt. Sent as ``system=<intent>`` + ``user=""``, Anthropic lifts the
system message out, drops the empty turn and answers 400 "at least one message is required".
These tests pin the mapping: an empty context carries the intent as the one user turn, and every
non-empty context keeps today's bytes exactly.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_aigateway_connector import _MODEL, _PNG_DATA_URI, _MockAigateway, _picture_case

from screamingface_engine.world.config import routes_for
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _messages,
    _ModelEndpoint,
)
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_FUSION_INTENT = "m1:\nYES\n\nm2:\nYES\n\nYou are the fusion synthesizer. Give one final answer."


async def _sent_messages(context: str, intent: str) -> list[dict[str, Any]]:
    """Send one call through the connector; return the messages the gateway got."""

    gw = _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        handler = _ModelEndpoint(
            http_client=client,
            cfg=cfg,
            routes=routes_for(gw.models),
            tavily_http=None,
            tavily_api_key=None,
        )
        assert (
            await handler(Request(path=f"/{_MODEL}", context=context, intent=intent, params={}))
            == "42"
        )
    (post,) = gw.posts_to(_MODEL)
    return json.loads(post.content)["messages"]


@pytest.mark.parametrize("context", ["", None], ids=["empty", "none"])
async def test_an_empty_context_carries_the_intent_as_the_user_turn(context: str | None) -> None:
    # STORY: as a researcher fusing a text-only ensemble on an Anthropic synthesizer, the reduce
    # answers instead of failing with 400 "at least one message is required".
    assert _messages(context, _FUSION_INTENT) == [{"role": "user", "content": _FUSION_INTENT}]


async def test_the_gateway_never_receives_an_empty_user_turn() -> None:
    # INVARIANT: no message the gateway receives has empty content when an intent exists.
    messages = await _sent_messages("", _FUSION_INTENT)

    assert messages == [{"role": "user", "content": _FUSION_INTENT}]


async def test_a_non_empty_context_keeps_todays_bytes() -> None:
    # WHY: every run that worked before keeps its exact chat body, so its gateway cache key and
    # its frozen captures stay valid.
    messages = await _sent_messages("What is 6 times 7?", "Answer with a number.")

    assert messages == [
        {"role": "system", "content": "Answer with a number."},
        {"role": "user", "content": "What is 6 times 7?"},
    ]


async def test_a_non_empty_context_without_intent_keeps_todays_bytes() -> None:
    assert _messages("What is 6 times 7?", None) == [
        {"role": "user", "content": "What is 6 times 7?"}
    ]


async def test_a_picture_envelope_keeps_its_system_and_native_messages() -> None:
    # WHY: with attachments the user turn carries parts, so the envelope path is unchanged.
    assert _messages(_picture_case(), "Answer briefly.") == [
        {"role": "system", "content": "Answer briefly."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is the height of the tallest bar?"},
                {"type": "image_url", "image_url": {"url": _PNG_DATA_URI}},
            ],
        },
    ]


async def test_no_intent_and_no_context_is_unchanged() -> None:
    # WHY: with neither an intent nor a context there is nothing to carry; this unit does not
    # invent a refusal for that call, so it keeps today's body.
    assert _messages("", None) == [{"role": "user", "content": ""}]
