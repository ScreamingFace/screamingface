"""A Case Result echoes its Case input with each picture shown as a placeholder (OME-1271).

FEATURE: every Case Result carries the Case input it answered, so a researcher can read the
question beside the answer. STORY: as a researcher running a picture Benchmark (LAB-Bench FigQA:
181 Cases, about 330 MB of pictures), my notebook gets a short placeholder for each picture,
not its base64, so the report fits in memory; the placeholder's sha256 still proves a picture I
open later is the one the model saw.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)
from screamingface_engine.benchmarks.echoed_input import echoed_input

# The 8-byte PNG signature, and the sha256 of those 8 bytes (pinned in
# test_media_placeholder_conformance.py on both sides).
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PNG_SHA256 = "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6"
# The 8 bytes b"%PDF-1.4", and their sha256 (pinned in test_media_placeholder.py).
_PDF = "data:application/pdf;base64,JVBERi0xLjQ="
_PDF_SHA256 = "e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e"
_QUESTION = {"type": "text", "text": "What is the height of the tallest bar?"}


def _v2(*messages: dict[str, Any]) -> str:
    """Seal messages into a v2 envelope, compact like the importer writes it."""

    return json.dumps(
        {"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": list(messages)}, separators=(",", ":")
    )


def _user(*parts: object) -> dict[str, Any]:
    """One user message whose content is a list of parts."""

    return {"role": "user", "content": list(parts)}


def test_a_picture_is_echoed_as_its_placeholder_and_its_base64_is_gone() -> None:
    # INVARIANT: the bytes are measured decoded (8, not the 12 letters of base64), and the
    # sha256 stays, because a picture opened from a Case Result is checked against it.
    case_input: str = _v2(_user(_QUESTION, {"type": "image_url", "image_url": {"url": _PNG}}))

    echoed: str = echoed_input(case_input)

    assert "base64," not in echoed
    assert json.loads(echoed) == {
        "schema": CANDIDATE_INPUT_V2_SCHEMA,
        "messages": [
            {
                "role": "user",
                "content": [
                    _QUESTION,
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": {
                                "placeholder": "image",
                                "media_type": "image/png",
                                "size": 8,
                                "sha256": _PNG_SHA256,
                            }
                        },
                    },
                ],
            }
        ],
    }


def test_the_echo_is_compact_json_like_the_importer_writes() -> None:
    # WHY pin the bytes: the SDK's twin (packages/screamingface/tests/unit/
    # test_media_placeholder_conformance.py) reads these same two texts, so a change of shape
    # on either side goes red in that side's lane.
    picture: str = _v2(_user({"type": "image_url", "image_url": {"url": _PNG}}))
    paper: str = _v2(_user({"type": "file", "file": {"file_data": _PDF, "filename": "paper.pdf"}}))

    assert echoed_input(picture) == (
        '{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":'
        '[{"type":"image_url","image_url":{"url":{"placeholder":"image","media_type":"image/png",'
        f'"size":8,"sha256":"{_PNG_SHA256}"'
        "}}}]}]}"
    )
    assert echoed_input(paper) == (
        '{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":'
        '[{"type":"file","file":{"file_data":{"placeholder":"file","media_type":"application/pdf",'
        f'"size":8,"sha256":"{_PDF_SHA256}",'
        '"filename":"paper.pdf"},"filename":"paper.pdf"}}]}]}'
    )


def test_a_file_part_keeps_its_filename_and_a_picture_keeps_its_detail() -> None:
    # WHY keep them: the placeholder replaces only the bytes; every other field of the part is
    # the Case as written, and the filename is how a researcher recognises the paper.
    case_input: str = _v2(
        _user(
            {"type": "file", "file": {"file_data": _PDF, "filename": "paper.pdf"}},
            {"type": "image_url", "image_url": {"url": _PNG, "detail": "high"}},
            _QUESTION,
        )
    )

    content: list[dict[str, Any]] = json.loads(echoed_input(case_input))["messages"][0]["content"]

    assert content[0] == {
        "type": "file",
        "file": {
            "file_data": {
                "placeholder": "file",
                "media_type": "application/pdf",
                "size": 8,
                "sha256": _PDF_SHA256,
                "filename": "paper.pdf",
            },
            "filename": "paper.pdf",
        },
    }
    assert content[1]["image_url"]["detail"] == "high"
    assert content[1]["image_url"]["url"]["sha256"] == _PNG_SHA256
    assert content[2] == _QUESTION


def test_text_messages_of_a_picture_case_keep_their_order_and_text() -> None:
    # INVARIANT: the Case's own layout is kept (system turn, then the picture turn), so the
    # echo reads as the Case did, less the bytes.
    case_input: str = _v2(
        {"role": "system", "content": "Answer with a number."},
        _user(_QUESTION, {"type": "image_url", "image_url": {"url": _PNG}}),
    )

    messages: list[dict[str, Any]] = json.loads(echoed_input(case_input))["messages"]

    assert messages[0] == {"role": "system", "content": "Answer with a number."}
    assert [part["type"] for part in messages[1]["content"]] == ["text", "image_url"]


@pytest.mark.parametrize(
    "case_input",
    [
        "What is 6 times 7?",
        '{"question": "What is 6 times 7?"}',
        # A v1 conversation, spelled with spaces: the echo must not re-encode it.
        json.dumps(
            {
                "schema": CANDIDATE_INPUT_SCHEMA,
                "messages": [{"role": "user", "content": "What is 6 times 7?"}],
            }
        ),
    ],
)
def test_a_text_only_case_is_echoed_as_the_exact_same_string(case_input: str) -> None:
    # INVARIANT: every text Benchmark's Case Results stay byte-identical to before this change.
    assert echoed_input(case_input) == case_input


@pytest.mark.parametrize(
    "case_input",
    [
        # A picture that is not in the standard spelling (no padding).
        _v2(
            _user({"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo"}})
        ),
        # An https:// picture the reader refuses.
        _v2(_user({"type": "image_url", "image_url": {"url": "https://example.com/a.png"}})),
        # A version of the envelope this engine does not read.
        json.dumps(
            {
                "schema": "screamingface.candidate-input.v3",
                "messages": [_user({"type": "image_url", "image_url": {"url": _PNG}})],
            }
        ),
    ],
)
def test_a_case_the_reader_refuses_is_echoed_as_one_line_without_its_bytes(
    case_input: str,
) -> None:
    # WHY not the raw text: a refused Case already failed when the Candidate was asked, and its
    # raw text may hold megabytes of base64; the line names the rule it broke instead.
    echoed: str = echoed_input(case_input)

    assert echoed.startswith("[Case input not shown: ")
    assert "base64" not in echoed
    assert "iVBORw0KGgo" not in echoed
    assert "example.com" not in echoed
