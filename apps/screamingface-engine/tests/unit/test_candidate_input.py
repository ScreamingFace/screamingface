"""The candidate-input envelope rules (OME-1678).

The v2 shape is §2.7 of the file-input spec on #1450, first proposed in
https://github.com/ScreamingFace/screamingface/pull/1450#issuecomment-6286823021.

A Case input is either a plain prompt or an envelope naming a candidate-input schema. v1 carries
text messages; v2 lets a user message carry pictures and PDFs as inline ``data:`` URIs. These
tests pin what each version accepts and how a broken envelope is refused.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)

# WHY a short stand-in payload: the module checks only the data: prefix and never decodes, so
# any non-empty base64 text stands in for a real picture.
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PDF = "data:application/pdf;base64,JVBERi0xLjQ="
_TEXT = {"type": "text", "text": "What is the height of the tallest bar?"}
_IMAGE = {"type": "image_url", "image_url": {"url": _PNG}}


def _v2(*messages: dict[str, Any]) -> str:
    """Seal messages into a v2 envelope, compact like the importer writes it."""

    return json.dumps(
        {"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": list(messages)}, separators=(",", ":")
    )


def _user(*parts: object) -> dict[str, Any]:
    """One user message whose content is a list of parts."""

    return {"role": "user", "content": list(parts)}


def test_plain_text_and_other_json_are_prompts_not_envelopes() -> None:
    # WHY: a prompt that happens to be JSON must reach the model as written, as it always has.
    assert parse_candidate_input("What is 6 times 7?") is None
    assert parse_candidate_input('{"question": "What is 6 times 7?"}') is None
    assert parse_candidate_input("[1, 2]") is None
    assert parse_candidate_input("") is None
    assert parse_candidate_input(None) is None


def test_v1_messages_come_back_exactly_as_written() -> None:
    # INVARIANT: v1 Cases send byte-identical requests, so every existing golden replays.
    messages = [
        {"role": "user", "content": "My knee hurts."},
        {"role": "assistant", "content": "Since when?"},
        {"role": "user", "content": "Two days."},
    ]
    text = json.dumps({"schema": CANDIDATE_INPUT_SCHEMA, "messages": messages})

    # WHY compare serialized text and not only dicts: dict == ignores key order, and a swapped
    # role/content order would change every recorded request body while == stayed green.
    assert json.dumps(parse_candidate_input(text)) == json.dumps(messages)


def test_v2_user_message_keeps_its_text_and_picture_parts_in_order() -> None:
    text = _v2(
        {"role": "system", "content": "Answer with a number."},
        _user(_TEXT, {"type": "image_url", "image_url": {"url": _PNG, "detail": "high"}}),
    )

    assert parse_candidate_input(text) == [
        {"role": "system", "content": "Answer with a number."},
        {
            "role": "user",
            "content": [_TEXT, {"type": "image_url", "image_url": {"url": _PNG, "detail": "high"}}],
        },
    ]


def test_v2_pdf_file_part_keeps_its_filename() -> None:
    part = {"type": "file", "file": {"file_data": _PDF, "filename": "a.pdf"}}

    assert parse_candidate_input(_v2(_user(_TEXT, part))) == [
        {"role": "user", "content": [_TEXT, part]}
    ]


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/gif", "image/webp"])
def test_v2_accepts_the_four_picture_types_every_provider_takes(mime: str) -> None:
    part = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,AAAA"}}

    assert parse_candidate_input(_v2(_user(part))) == [{"role": "user", "content": [part]}]


def test_v2_parses_an_mmmu_sized_case() -> None:
    # WHY 3.8 MB: MMMU's largest Case (validation_Geography_16) is 3.78 MB inline.
    big = "data:image/png;base64," + "A" * (3_800_000)
    part = {"type": "image_url", "image_url": {"url": big}}

    assert parse_candidate_input(_v2(_user(_TEXT, part))) == [
        {"role": "user", "content": [_TEXT, part]}
    ]


def test_unknown_candidate_input_version_is_refused_by_name() -> None:
    text = json.dumps({"schema": "screamingface.candidate-input.v3", "messages": []})

    with pytest.raises(
        CandidateInputError, match=r"unsupported schema 'screamingface\.candidate-input\.v3'"
    ):
        parse_candidate_input(text)


@pytest.mark.parametrize(
    ("part", "reason"),
    [
        ({"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}, "data: URI"),
        ({"type": "image_url", "image_url": {"url": "/blob/sha256/9f86d081"}}, "data: URI"),
        ({"type": "image_url", "image_url": {"url": "data:image/png;base64,"}}, "data: URI"),
        (
            {"type": "image_url", "image_url": {"url": "data:image/svg+xml;base64,PHN2Zz4="}},
            "picture type",
        ),
        ({"type": "image_url", "image_url": {"url": _PDF}}, "picture type"),
        ({"type": "image_url", "image_url": {"url": _PNG, "detail": "original"}}, "detail"),
        ({"type": "image_url", "image_url": {"url": _PNG, "alt": "x"}}, "image_url"),
        ({"type": "image_url", "image_url": _PNG}, "image_url"),
        ({"type": "file", "file": {"file_data": _PNG}}, "application/pdf"),
        ({"type": "file", "file": {"file_data": "https://example.com/a.pdf"}}, "data: URI"),
        ({"type": "file", "file": {"file_data": _PDF, "filename": ""}}, "filename"),
        ({"type": "file", "file": {"file_id": "file-123"}}, "file"),
        ({"type": "input_audio", "input_audio": {"data": "AAAA"}}, "unsupported part type"),
        # A URL where the part type belongs is named by its type, never repeated.
        ({"type": "https://example.com/a.png"}, "unsupported part type <str>"),
        ({"type": "text", "text": ""}, "text"),
        ({"type": "text", "text": "hi", "cache_control": {}}, "text"),
    ],
)
def test_a_part_that_breaks_a_rule_is_refused_by_position_never_echoing_its_bytes(
    part: dict[str, Any], reason: str
) -> None:
    with pytest.raises(CandidateInputError, match=reason) as caught:
        parse_candidate_input(_v2(_user(_TEXT, part)))

    message = str(caught.value)
    assert "message 0 part 1" in message
    # INVARIANT: a refusal never carries the URL or the base64, so a log line stays small and
    # a private picture never leaks into a report.
    for leaked in ("example.com", "/blob/", "base64", "iVBOR", "JVBER", "PHN2Zz4"):
        assert leaked not in message


_BIG_PNG = "data:image/png;base64," + "iVBORw0KGgo" * 100_000


@pytest.mark.parametrize(
    "envelope",
    [
        # An importer bug that swaps a message's role and content: the role holds the picture.
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [
                {"role": [{"type": "image_url", "image_url": {"url": _BIG_PNG}}], "content": "hi"}
            ],
        },
        # A role or schema that is long text, not a name.
        {"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": [{"role": _BIG_PNG, "content": "hi"}]},
        {"schema": "screamingface.candidate-input." + _BIG_PNG, "messages": []},
    ],
)
def test_a_refusal_never_repeats_a_misplaced_picture(envelope: dict[str, Any]) -> None:
    # INVARIANT: a value in the wrong field is named by its type, so a refusal stays one short
    # line and never carries a picture into a log or a report.
    with pytest.raises(CandidateInputError) as caught:
        parse_candidate_input(json.dumps(envelope))

    message = str(caught.value)
    assert "base64" not in message
    assert "iVBOR" not in message
    assert len(message) < 120


@pytest.mark.parametrize(
    "text",
    [
        '{"schema": ' + "1" * 5000 + "}",  # past Python's int digit limit: a plain ValueError
        '{"a":' + "[" * 100_000 + "]" * 100_000 + "}",  # deep enough to raise RecursionError
    ],
)
def test_json_that_python_cannot_load_is_a_prompt_not_a_crash(text: str) -> None:
    # WHY: not an envelope, so it reaches the model as written, as other non-envelope text does.
    assert parse_candidate_input(text) is None


@pytest.mark.parametrize("role", ["system", "developer", "assistant"])
def test_pictures_go_in_user_messages_only(role: str) -> None:
    # WHY: Anthropic OAuth drops non-text parts from system messages (§1), and a picture the
    # model never saw would grade as a wrong answer instead of failing.
    text = _v2({"role": role, "content": [_IMAGE]}, _user(_TEXT, _IMAGE))

    with pytest.raises(
        CandidateInputError, match="message 0: pictures and files go in user messages only"
    ):
        parse_candidate_input(text)


def test_a_v2_envelope_with_only_text_is_refused() -> None:
    # WHY: a text-only Case stays v1, so one Case has exactly one valid encoding.
    text = _v2({"role": "user", "content": "What is 6 times 7?"})

    with pytest.raises(CandidateInputError, match="carries no picture or file; write it as v1"):
        parse_candidate_input(text)


def test_a_part_list_with_only_text_is_refused() -> None:
    # WHY: a message without a picture is written as a plain string, never as text parts, so a
    # message has one encoding too.
    text = _v2({"role": "user", "content": [_TEXT]}, _user(_TEXT, _IMAGE))

    with pytest.raises(
        CandidateInputError, match="message 0: a part list must carry a picture or file"
    ):
        parse_candidate_input(text)


@pytest.mark.parametrize(
    ("envelope", "reason"),
    [
        ({}, "must contain only schema and messages"),
        (
            {"messages": [{"role": "user", "content": "hi"}], "extra": 1},
            "must contain only schema and messages",
        ),
        ({"messages": []}, "messages must be a non-empty array"),
        ({"messages": [{"role": "user"}]}, "message 0 must contain exactly role and content"),
        (
            {"messages": [{"role": "tool", "content": "hi"}]},
            "message 0 has unsupported role 'tool'",
        ),
        (
            {"messages": [{"role": "user", "content": 7}]},
            "message 0 content must be text or a part list",
        ),
        (
            {"messages": [{"role": "user", "content": []}]},
            "message 0: a part list must not be empty",
        ),
        ({"messages": [_user(_TEXT, "not a part")]}, "message 0 part 1 must be an object"),
    ],
)
def test_a_malformed_v2_envelope_is_refused(envelope: dict[str, Any], reason: str) -> None:
    body: dict[str, Any] = {"schema": CANDIDATE_INPUT_V2_SCHEMA, **envelope}

    with pytest.raises(CandidateInputError, match=reason):
        parse_candidate_input(json.dumps(body))


def test_v1_content_must_stay_text() -> None:
    # INVARIANT: v1 never carries parts; a list there is a v2 Case written under the wrong name.
    text = json.dumps({"schema": CANDIDATE_INPUT_SCHEMA, "messages": [_user(_TEXT, _IMAGE)]})

    with pytest.raises(CandidateInputError, match="message 0 content must be text"):
        parse_candidate_input(text)
