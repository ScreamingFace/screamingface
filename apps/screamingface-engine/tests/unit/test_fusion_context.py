"""A Fusion's synthesizer sees the Case's pictures (OME-1679).

A Fusion has member models answer a Case, then a synthesizer writes the final answer from their
answers. The synthesizer reads one JSON text, ``{"input": <the Case input>, "outputs": …}``, built
by url4 at run time. These tests pin what the connector sends for that text: on a picture Case,
the pictures as image parts and the text with each picture shown as a placeholder; on any other
Case, today's bytes exactly.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_aigateway_connector import _MODEL, _MockAigateway

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine.world.config import routes_for
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _messages,
    _ModelEndpoint,
    build_aigateway_world,
)
from url4 import RelExpr, expr, render, src, struct, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

# The 8-byte PNG signature. Its full placeholder is pinned in test_media_placeholder.py; the
# synthesizer's text shows it less the digest.
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PNG_PLACEHOLDER = {"placeholder": "image", "index": 1, "media_type": "image/png", "size": 8}
_QUESTION = {"type": "text", "text": "What is the height of the tallest bar?"}
_IMAGE = {"type": "image_url", "image_url": {"url": _PNG, "detail": "low"}}
_OUTPUTS = {"member_1": "about 42", "member_2": "42"}


def _envelope(schema: str, *messages: dict[str, Any]) -> str:
    """Seal messages into an envelope, compact like the importer writes it."""

    return json.dumps({"schema": schema, "messages": list(messages)}, separators=(",", ":"))


def _picture_case() -> str:
    """A v2 Case: a system line, then one user message holding a question and one PNG."""

    return _envelope(
        CANDIDATE_INPUT_V2_SCHEMA,
        {"role": "system", "content": "You read charts."},
        {"role": "user", "content": [_QUESTION, _IMAGE]},
    )


def _fusion_context(case_input: str, **rest: object) -> str:
    """The text a synthesizer receives. WHY ``json.dumps`` with its defaults: that is exactly how
    url4 renders the Fusion's ``{input, outputs}`` struct at run time (``StructNode.resolve``);
    ``test_the_context_url4_builds_reaches_the_gateway_with_its_picture`` checks it end to end.
    """

    return json.dumps({"input": case_input, **(rest or {"outputs": _OUTPUTS})})


def _shown_case() -> str:
    """The picture Case as the synthesizer's text shows it: every picture is its placeholder."""

    return _envelope(
        CANDIDATE_INPUT_V2_SCHEMA,
        {"role": "system", "content": "You read charts."},
        {
            "role": "user",
            "content": [
                _QUESTION,
                {"type": "image_url", "image_url": {"url": _PNG_PLACEHOLDER, "detail": "low"}},
            ],
        },
    )


async def _sent_messages(context: str) -> list[dict[str, Any]]:
    """Send one synthesizer call through the connector; return the messages the gateway got."""

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
            await handler(
                Request(path=f"/{_MODEL}", context=context, intent="Synthesize.", params={})
            )
            == "42"
        )
    (post,) = gw.posts_to(_MODEL)
    return json.loads(post.content)["messages"]


async def test_a_picture_fusion_sends_the_synthesizer_its_picture() -> None:
    # STORY: as a researcher running a Fusion on a chart Benchmark, the synthesizer judges the
    # members' answers while looking at the chart, not at a megabyte of base64 text.
    messages = await _sent_messages(_fusion_context(_picture_case()))

    # INVARIANT (spec F2): the Case's pictures first, then today's {input, outputs} text with
    # only each picture's url replaced; member outputs are text and add no parts.
    assert messages == [
        {"role": "system", "content": "Synthesize."},
        {
            "role": "user",
            "content": [
                _IMAGE,
                {"type": "text", "text": json.dumps({"input": _shown_case(), "outputs": _OUTPUTS})},
            ],
        },
    ]
    assert "base64," not in messages[1]["content"][1]["text"]


async def test_the_synthesizer_reads_no_digest() -> None:
    # WHY: the synthesizer cannot hash the picture it is shown, and a digest in its text reads as
    # a reference to fetch, which the spec's Fusion paragraph forbids. Results keep the digest,
    # so a picture opened from a Case Result can be checked against it; only the model's text
    # leaves it out.
    messages = await _sent_messages(_fusion_context(_picture_case()))

    assert "sha256" not in messages[1]["content"][1]["text"]


async def test_each_picture_is_numbered_in_case_order() -> None:
    # WHY: the synthesizer gets every part first and the text after, so it pairs part k with
    # placeholder k. The number makes that pairing explicit instead of counted, so two pictures of
    # one type and size are never mixed up. 1-based, and counted across messages, files included.
    pdf = {
        "type": "file",
        "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQ=", "filename": "paper.pdf"},
    }
    case = _envelope(
        CANDIDATE_INPUT_V2_SCHEMA,
        {"role": "user", "content": [_QUESTION, _IMAGE]},
        {"role": "user", "content": [{"type": "text", "text": "And this?"}, pdf, _IMAGE]},
    )

    content = (await _sent_messages(_fusion_context(case)))[1]["content"]

    media, text = content[:-1], content[-1]["text"]
    assert media == [_IMAGE, pdf, _IMAGE]
    shown = json.loads(json.loads(text)["input"])["messages"]
    placeholders = [
        part["image_url"]["url"] if part["type"] == "image_url" else part["file"]["file_data"]
        for message in shown
        for part in message["content"]
        if part["type"] != "text"
    ]
    assert len(placeholders) == len(media)
    assert [(p["index"], p["media_type"]) for p in placeholders] == [
        (1, "image/png"),
        (2, "application/pdf"),
        (3, "image/png"),
    ]
    # INVARIANT: the number reads right after the kind, before the measures.
    assert list(placeholders[1]) == ["placeholder", "index", "media_type", "size", "filename"]


@pytest.mark.parametrize(
    "case_input",
    [
        "What is 6 times 7?",
        _envelope(CANDIDATE_INPUT_SCHEMA, {"role": "user", "content": "What is 6 times 7?"}),
    ],
    ids=["plain prompt", "v1 conversation"],
)
async def test_a_text_only_fusion_sends_todays_exact_bytes(case_input: str) -> None:
    # INVARIANT (OME-1679 acceptance 2): a Case without pictures reaches the gateway as the same
    # one text message it always did, so every recorded golden still replays.
    context = _fusion_context(case_input)

    assert await _sent_messages(context) == [
        {"role": "system", "content": "Synthesize."},
        {"role": "user", "content": context},
    ]


async def test_a_reducer_signal_call_gets_the_picture_too() -> None:
    # WHY: a reducer's signal calls read the same {input, …} text, with the quorum panel in place
    # of outputs, and run as Candidate calls; on a picture Case they need the picture as well.
    panel = json.dumps([{"name": "member_1", "output": "42"}])

    messages = await _sent_messages(_fusion_context(_picture_case(), panel=panel))

    assert messages[1]["content"] == [
        _IMAGE,
        {"type": "text", "text": json.dumps({"input": _shown_case(), "panel": panel})},
    ]


def _fusion_recipe() -> str:
    """One member, then a synthesizer over ``{"input": "$input", ...}``, as the SDK compiles it."""

    member = src(
        RelExpr(path=f"/{_MODEL}", context="$input", intent=text("Answer.")),
        name="model_1",
        weight=0.0,
    )
    context = render(struct({"input": "$input", "outputs": {"member_1": "$model_1"}}))
    synthesizer = src(
        RelExpr(path=f"/{_MODEL}", context=context, intent=text("Synthesize.")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(member, synthesizer, intent=text("$synthesis_1")))


async def test_the_context_url4_builds_reaches_the_gateway_with_its_picture() -> None:
    # WHY end to end through "$input": the SDK writes a reference, not the Case, and url4
    # substitutes it at run time. A literal envelope in the struct takes a different url4 branch,
    # so only this proves the text the connector reads is the one a real Fusion hands it.
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            await evaluate_candidate_recipe(world.node, _fusion_recipe(), _picture_case())
        finally:
            await world.aclose()

    member_post, synthesizer_post = gw.posts_to(_MODEL)
    member = json.loads(member_post.content)["messages"][-1]["content"]
    content = json.loads(synthesizer_post.content)["messages"][-1]["content"]
    assert member[-1] == _IMAGE
    assert content[0] == _IMAGE
    assert json.loads(content[1]["text"]) == {
        "input": _shown_case(),
        "outputs": {"member_1": "42"},
    }


async def test_a_broken_picture_in_the_fusion_input_is_refused_before_any_call() -> None:
    # INVARIANT: the synthesizer reads the Case by the members' rules. A Case naming an https://
    # picture is refused by name, never fetched and never sent.
    context = _fusion_context(_picture_case().replace(_PNG, "https://insecure-website.com/a.png"))
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

        with pytest.raises(ResolutionError, match="the Fusion input, message 1 part 1") as caught:
            await handler(Request(path=f"/{_MODEL}", context=context, intent="", params={}))

    assert gw.posts_to(_MODEL) == []
    assert caught.value.code == "invalid_candidate_input"
    assert "insecure-website.com" not in str(caught.value)


@pytest.mark.parametrize(
    "context",
    [
        json.dumps({"outputs": _OUTPUTS}),
        json.dumps({"input": 7, "outputs": _OUTPUTS}),
        json.dumps({"input": "not an envelope", "outputs": _OUTPUTS}),
        '{"input": "unterminated',
        # WHY compact spacing: proves this path never re-encodes text it does not change.
        '{"input":"What is 6 times 7?","outputs":{"member_1":"42"}}',
    ],
    ids=["no input", "input not text", "input a plain prompt", "not JSON", "compact spacing"],
)
async def test_any_other_json_text_is_sent_as_written(context: str) -> None:
    # WHY: the engine learns one key, `input`, and nothing else about recipes; anything that is
    # not a picture Case under it keeps today's path.
    assert _messages(context, None) == [{"role": "user", "content": context}]


async def test_a_grading_call_keeps_todays_path() -> None:
    # WHY: judges never receive picture parts (spec D6), and what a grader reads of a picture Case
    # is OME-1271 PR 3's change. Under grading this path stays off.
    context = _fusion_context(_picture_case())

    with grading_call_scope("case-1"):
        assert _messages(context, None) == [{"role": "user", "content": context}]
