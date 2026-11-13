"""Every model call of a url4 run sees the run's files as content parts (OME-1545).

The url4 run carries a frozen, ordered ``attachments[]`` side-channel (``OME-1543``) and hands it to
each in-process model call as ``Request.attachments``. These tests pin what the connector sends for
it (spec ``docs/spec/2026-10-16-OME-1535-file-input-execution.md`` F2, F3, §2.7 gate 2): the files
lead the last user message as ``image_url`` / ``file`` parts with canonical ``data:`` URIs, a
text-only call is byte-identical to today, and a grading call carrying files is refused by name.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from test_aigateway_connector import _MODEL, _MockAigateway
from test_fusion_context import _fusion_context, _fusion_recipe, _picture_case

from screamingface_engine.benchmarks.candidate_input import _DATA_URI_RE
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine.world.attachment_parts import (
    BlobReader,
    attachment_parts,
    bound_blob_reader,
    canonical_data_uri,
    place_on_last_user_message,
)
from screamingface_engine.world.config import routes_for
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _ModelEndpoint,
    build_aigateway_world,
)
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.dag.attachments import bind_run_files
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_PNG_BYTES = b"\x89PNG\r\n\x1a\n"
_PDF_BYTES = b"%PDF-1.4"
_PNG_URI = "data:image/png;base64,iVBORw0KGgo="
_PDF_URI = "data:application/pdf;base64,JVBERi0xLjQ="


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _png(**extra: Any) -> Attachment:
    return Attachment(digest=_digest(_PNG_BYTES), media_type="image/png", body=_PNG_BYTES, **extra)


def _pdf(**extra: Any) -> Attachment:
    return Attachment(
        digest=_digest(_PDF_BYTES), media_type="application/pdf", body=_PDF_BYTES, **extra
    )


class _Reader:
    """A run-scoped store holding ``blobs``; records every digest it is asked for."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.reads: list[str] = []

    async def read(self, digest: str) -> bytes | None:
        self.reads.append(digest)
        return self.blobs.get(digest)


async def _send(
    context: str,
    attachments: tuple[Attachment, ...] = (),
    *,
    intent: str = "Answer.",
    reader: BlobReader | None = None,
    gw: _MockAigateway | None = None,
) -> tuple[_MockAigateway, Any]:
    gw = gw or _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        handler = _ModelEndpoint(
            http_client=client,
            cfg=cfg,
            routes=routes_for(gw.models),
            tavily_http=None,
            tavily_api_key=None,
        )
        request = Request(
            path=f"/{_MODEL}", context=context, intent=intent, params={}, attachments=attachments
        )
        if reader is None:
            result = await handler(request)
        else:
            with bound_blob_reader(reader):
                result = await handler(request)
    return gw, result


async def _sent_messages(context: str, *attachments: Attachment, **kw: Any) -> list[dict]:
    gw, result = await _send(context, attachments, **kw)
    assert result == "42"
    (post,) = gw.posts_to(_MODEL)
    return json.loads(post.content)["messages"]


async def test_an_image_attachment_leads_the_user_message() -> None:
    # STORY: as an ensemble author who wrote `(img:0.5:src=/blob/sha256/…)!'Describe'`, the model
    # gets the picture itself, not a ref or base64 text.
    messages = await _sent_messages("Describe the chart.", _png())

    assert messages == [
        {"role": "system", "content": "Answer."},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _PNG_URI}},
                {"type": "text", "text": "Describe the chart."},
            ],
        },
    ]


async def test_a_pdf_attachment_is_a_file_part_with_its_filename() -> None:
    messages = await _sent_messages("Summarize.", _pdf(filename="paper.pdf"))

    assert messages[-1]["content"] == [
        {"type": "file", "file": {"file_data": _PDF_URI, "filename": "paper.pdf"}},
        {"type": "text", "text": "Summarize."},
    ]


async def test_two_attachments_keep_attachments_order_and_carry_detail() -> None:
    # INVARIANT (F2): parts in attachments[] order, then the text; `detail` rides on image_url.
    messages = await _sent_messages("Compare.", _pdf(), _png(detail="high"))

    assert messages[-1]["content"] == [
        {"type": "file", "file": {"file_data": _PDF_URI}},
        {"type": "image_url", "image_url": {"url": _PNG_URI, "detail": "high"}},
        {"type": "text", "text": "Compare."},
    ]


async def test_a_text_only_call_sends_todays_exact_bytes() -> None:
    # INVARIANT (F2): a call with no attachments sends `content` as a plain string, exactly as
    # before OME-1545 — these bytes were captured from the connector before the change.
    gw, _ = await _send("What is 6 times 7?")

    (post,) = gw.posts_to(_MODEL)
    assert post.content == (
        b'{"model":"anthropic/claude-haiku-4-5","messages":[{"role":"system","content":"Answer."},'
        b'{"role":"user","content":"What is 6 times 7?"}]}'
    )


async def test_a_grading_call_carrying_attachments_is_refused_before_any_read() -> None:
    # INVARIANT (spec §2.7 gate 2, D6; F2 Judge): under OME-1271 v1 the grader receives no files.
    # A grading call that would carry one is refused by name, before any byte is read or sent.
    reader = _Reader({})
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    with grading_call_scope("case-1"), pytest.raises(ResolutionError) as caught:
        await _send("Grade it.", (_png(),), reader=reader, gw=gw)

    assert caught.value.code == "invalid_candidate_input"
    assert "judges read text only" in str(caught.value)
    assert reader.reads == []
    assert gw.posts_to(_MODEL) == []


async def test_a_grading_call_without_attachments_keeps_todays_path() -> None:
    with grading_call_scope("case-1"):
        messages = await _sent_messages("Grade it.")

    assert messages[-1] == {"role": "user", "content": "Grade it."}


@pytest.mark.parametrize(
    ("media_type", "expected_prefix"),
    [
        ("image/png", "data:image/png;base64,"),
        ("IMAGE/PNG", "data:image/png;base64,"),
        ("Application/PDF; charset=binary", "data:application/pdf;base64,"),
    ],
)
async def test_the_data_uri_is_canonical(media_type: str, expected_prefix: str) -> None:
    # INVARIANT (F3): lowercased media type, no parameters, standard padded base64 with no line
    # breaks — 100 bytes would wrap under MIME base64 and needs one `=` of padding here.
    body = bytes(range(100))

    uri = canonical_data_uri(media_type, body)

    payload = base64.b64encode(body).decode("ascii")
    assert uri == expected_prefix + payload
    assert "\n" not in uri and uri.endswith("=")
    assert "-" not in payload and "_" not in payload
    # WHY the engine's copy of the gateway pattern: a URI it builds must pass the gateway.
    assert _DATA_URI_RE.match(uri)


async def test_equal_files_give_byte_identical_parts() -> None:
    # WHY (F3): the gateway cache hashes the whole request, so equal files must encode equally
    # whatever spelling of the media type the source reported.
    one = Attachment(digest=_digest(_PNG_BYTES), media_type="image/PNG", body=_PNG_BYTES)
    two = Attachment(digest=_digest(_PNG_BYTES), media_type="image/png; q=1", body=_PNG_BYTES)

    assert await attachment_parts([one]) == await attachment_parts([two])


async def test_bytes_that_do_not_hash_to_the_digest_are_refused() -> None:
    # INVARIANT (F3 integrity): verified before use; the error names the digest, never the bytes.
    forged = Attachment(digest=_digest(b"other"), media_type="image/png", body=_PNG_BYTES)

    with pytest.raises(ResolutionError) as caught:
        await _send("Describe.", (forged,))

    assert caught.value.code == "x.blob_digest_mismatch"
    assert caught.value.permanent
    assert _digest(b"other") in str(caught.value)
    assert "PNG" not in str(caught.value)


async def test_a_ref_without_bytes_is_read_through_the_injected_reader() -> None:
    # WHY: when the snapshot holds only the ref, the engine wiring's run-scoped reader supplies
    # the bytes (OME-1540 store); the part is the same as for bytes the snapshot carried.
    ref = Attachment(digest=_digest(_PNG_BYTES), media_type="image/png")
    reader = _Reader({ref.digest: _PNG_BYTES})

    messages = await _sent_messages("Describe.", ref, reader=reader)

    assert reader.reads == [ref.digest]
    assert messages[-1]["content"][0] == {"type": "image_url", "image_url": {"url": _PNG_URI}}


@pytest.mark.parametrize("reader", [None, _Reader({})], ids=["no reader", "out of scope"])
async def test_an_unreadable_ref_is_source_not_found(reader: _Reader | None) -> None:
    ref = Attachment(digest=_digest(_PNG_BYTES), media_type="image/png")

    with pytest.raises(ResolutionError) as caught:
        await _send("Describe.", (ref,), reader=reader)

    assert caught.value.code == "source_not_found"
    assert caught.value.permanent


async def test_bytes_the_reader_returns_are_verified_too() -> None:
    ref = Attachment(digest=_digest(_PNG_BYTES), media_type="image/png")

    with pytest.raises(ResolutionError) as caught:
        await _send("Describe.", (ref,), reader=_Reader({ref.digest: b"corrupt"}))

    assert caught.value.code == "x.blob_digest_mismatch"


async def test_an_envelope_gets_the_parts_on_its_last_user_message_only() -> None:
    # INVARIANT (D3): earlier messages keep their text content unchanged.
    case = json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [
                {"role": "user", "content": "First question."},
                {"role": "assistant", "content": "First answer."},
                {"role": "user", "content": "Now this file."},
            ],
        }
    )

    messages = await _sent_messages(case, _pdf())

    assert messages[1:3] == [
        {"role": "user", "content": "First question."},
        {"role": "assistant", "content": "First answer."},
    ]
    assert messages[3]["content"] == [
        {"type": "file", "file": {"file_data": _PDF_URI}},
        {"type": "text", "text": "Now this file."},
    ]


async def test_a_synthesizer_on_a_picture_case_gets_url4_files_then_case_parts_then_text() -> None:
    # WHY (F2 Fusion): url4 attachments precede the {input, outputs} text; the Case's own parts
    # keep their order behind them.
    messages = await _sent_messages(_fusion_context(_picture_case()), _pdf(), intent="Synth.")

    content = messages[-1]["content"]
    assert content[0] == {"type": "file", "file": {"file_data": _PDF_URI}}
    assert content[1]["type"] == "image_url"
    assert content[2]["type"] == "text"
    assert len(content) == 3


async def test_a_reducer_signal_call_carries_the_same_parts() -> None:
    panel = json.dumps([{"name": "member_1", "output": "42"}])
    context = _fusion_context("What is 6 times 7?", panel=panel)

    messages = await _sent_messages(context, _png())

    assert messages[-1]["content"] == [
        {"type": "image_url", "image_url": {"url": _PNG_URI}},
        {"type": "text", "text": context},
    ]


async def test_every_model_call_of_a_url4_run_gets_the_runs_files() -> None:
    # STORY: end to end through url4 — a member and the Fusion synthesizer over it both read the
    # run's frozen attachments[] (bound as url4 binds them) and both send the picture first.
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with bind_run_files((_png(),)):
                await evaluate_candidate_recipe(world.node, _fusion_recipe(), "What is 6 x 7?")
        finally:
            await world.aclose()

    member_post, synthesizer_post = gw.posts_to(_MODEL)
    image = {"type": "image_url", "image_url": {"url": _PNG_URI}}
    member = json.loads(member_post.content)["messages"][-1]["content"]
    synthesizer = json.loads(synthesizer_post.content)["messages"][-1]["content"]
    assert member == [image, {"type": "text", "text": "What is 6 x 7?"}]
    assert synthesizer[0] == image
    assert json.loads(synthesizer[1]["text"])["outputs"] == {"member_1": "42"}


async def test_the_runs_bound_reader_serves_every_call_of_the_run() -> None:
    ref = Attachment(digest=_digest(_PDF_BYTES), media_type="application/pdf")
    reader = _Reader({ref.digest: _PDF_BYTES})
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "42"}, web_search=False)
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with bound_blob_reader(reader), bind_run_files((ref,)):
                await evaluate_candidate_recipe(world.node, _fusion_recipe(), "Summarize.")
        finally:
            await world.aclose()

    assert reader.reads == [ref.digest, ref.digest]
    for post in gw.posts_to(_MODEL):
        assert json.loads(post.content)["messages"][-1]["content"][0] == {
            "type": "file",
            "file": {"file_data": _PDF_URI},
        }


async def test_placing_no_parts_returns_the_messages_unchanged() -> None:
    messages = [{"role": "user", "content": "hi"}]

    assert place_on_last_user_message(messages, []) is messages


async def test_placing_parts_with_no_user_message_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="no user message"):
        place_on_last_user_message(
            [{"role": "system", "content": "x"}], [{"type": "text", "text": "y"}]
        )
