"""A Case Result shows each picture as a one-line placeholder, never as base64 (OME-1680).

FEATURE: picture Benchmarks carry their pictures inline, as ``data:`` URIs in the v2
candidate-input envelope (OME-1678). STORY: as a researcher reading a picture Case in my
notebook, I see the question and a short line naming each picture (file, type, size, digest)
instead of megabytes of base64.
"""

from __future__ import annotations

import base64
import json

import pytest

import screamingface as sf
from screamingface._ui.report_view import report_html

# A 300 KB "PNG" (the 8-byte signature, then zeros) and its sha256, pinned as literals so the
# test does not re-derive the digest the way the code does.
_PNG: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * (307_200 - 8)
_PNG_SHA256 = "fc2447cd696b58e9b606ffe9b49cd3cfc5fd2138064d7613d3a898f86cabc5a5"
_PNG_BASE64: str = base64.b64encode(_PNG).decode("ascii")
# A 2.4 MB "PDF" and its sha256, the same way.
_PDF: bytes = b"%PDF-1.7\n" + b"\x00" * (2_500_000 - 9)
_PDF_SHA256 = "f0c806e1a9bc5e0ba5af2c8d6812f32a6a2b362454e5843d765aa52e2071d461"

_QUESTION = "What is the height of the tallest bar?"
_PNG_LINE = "image/png · 300 KB · sha256 fc2447cd…"
_PDF_LINE = "paper.pdf · application/pdf · 2.4 MB · sha256 f0c806e1…"


def _v2(*content: object, schema: str = "screamingface.candidate-input.v2") -> str:
    """One user message holding ``content`` parts, sealed in a candidate-input envelope."""

    return json.dumps(
        {"schema": schema, "messages": [{"role": "user", "content": list(content)}]},
        separators=(",", ":"),
    )


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def _image(url: object) -> dict[str, object]:
    return {"type": "image_url", "image_url": {"url": url}}


def _case(value: str) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=1,
        input=value,
        output="42",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )


def _report(case: sf.CaseResult) -> sf.Report:
    from test_report import candidate

    result = candidate("opus", cases=(case,))
    return sf.Report(benchmark=result.benchmark, case_count=1, candidates=(result,))


def test_an_image_part_renders_as_a_placeholder_and_its_base64_appears_in_no_view() -> None:
    # INVARIANT (acceptance 1): every view of the input reads the one decode point, so the
    # picture is a placeholder in the turns, the transcript, the preview and the Report HTML.
    case = _case(_v2(_text(_QUESTION), _image(f"data:image/png;base64,{_PNG_BASE64}")))

    assert case.conversation == (("user", f"{_QUESTION}\n{_PNG_LINE}"),)
    assert case.display_input == f"user: {_QUESTION}\n{_PNG_LINE}"
    assert case.prompt_preview == f"{_QUESTION}\n{_PNG_LINE}"
    # WHY a 64-character slice: any run of the picture's base64 that long leaking into a view is
    # the bug, whichever end of it a renderer clips.
    leak: str = _PNG_BASE64[1000:1064]
    for view in (str(case.conversation), case.display_input, case.prompt_preview):
        assert leak not in view
    assert leak not in report_html(_report(case))
    # The raw wire value stays untouched for auditing and round-trips.
    assert _PNG_BASE64 in case.input


def test_a_placeholder_object_renders_the_line_its_data_uri_would() -> None:
    # INVARIANT: the engine will write a placeholder object where the url was (OME-1679); the
    # researcher sees the same line whichever form the result arrived in.
    placeholder: dict[str, object] = {
        "placeholder": "image",
        "media_type": "image/png",
        "size": 307_200,
        "sha256": _PNG_SHA256,
    }

    case = _case(_v2(_text(_QUESTION), _image(placeholder)))

    assert case.conversation == (("user", f"{_QUESTION}\n{_PNG_LINE}"),)


def test_a_file_part_leads_its_line_with_its_filename_in_both_forms() -> None:
    pdf_uri: str = "data:application/pdf;base64," + base64.b64encode(_PDF).decode("ascii")
    as_uri: dict[str, object] = {
        "type": "file",
        "file": {"file_data": pdf_uri, "filename": "paper.pdf"},
    }
    as_placeholder: dict[str, object] = {
        "type": "file",
        "file": {
            "file_data": {
                "placeholder": "file",
                "media_type": "application/pdf",
                "size": 2_500_000,
                "sha256": _PDF_SHA256,
                "filename": "paper.pdf",
            },
            "filename": "paper.pdf",
        },
    }

    for part in (as_uri, as_placeholder):
        assert _case(_v2(_text("Summarise the paper."), part)).conversation == (
            ("user", f"Summarise the paper.\n{_PDF_LINE}"),
        )


def test_a_file_placeholder_object_takes_the_parts_filename() -> None:
    # INVARIANT: the filename sits beside file_data on the part; replacing file_data with a
    # placeholder object must not lose it.
    part: dict[str, object] = {
        "type": "file",
        "file": {
            "file_data": {
                "placeholder": "file",
                "media_type": "application/pdf",
                "size": 2_500_000,
                "sha256": _PDF_SHA256,
            },
            "filename": "paper.pdf",
        },
    }

    assert _case(_v2(_text("Summarise the paper."), part)).conversation == (
        ("user", f"Summarise the paper.\n{_PDF_LINE}"),
    )


def test_line_wrapped_or_unpadded_base64_measures_the_same_picture() -> None:
    # INVARIANT: size and sha256 are those of the decoded bytes, decoded the way the engine's
    # request key decodes (whitespace dropped, padding restored), so the digest shown here is
    # the digest that keys the model call.
    wrapped: str = "\n".join(_PNG_BASE64[i : i + 76] for i in range(0, len(_PNG_BASE64), 76))
    unpadded: str = _PNG_BASE64.rstrip("=")

    for data in (wrapped, unpadded):
        case = _case(_v2(_text(_QUESTION), _image(f"data:image/png;base64,{data}")))
        assert case.conversation == (("user", f"{_QUESTION}\n{_PNG_LINE}"),)


def test_an_unknown_version_of_the_envelope_shows_one_line_never_its_base64() -> None:
    # INVARIANT: an engine newer than this SDK may send a version it cannot read. Its raw text
    # can be megabytes of base64, so the views show one line asking for an upgrade instead, and
    # never raise (raising would break the whole Report).
    value: str = _v2(
        _text(_QUESTION),
        _image(f"data:image/png;base64,{_PNG_BASE64}"),
        schema="screamingface.candidate-input.v3",
    )
    marker: str = (
        "unsupported candidate-input schema screamingface.candidate-input.v3"
        " — upgrade screamingface to view this input"
    )
    case = _case(value)

    assert case.conversation is None
    assert case.display_input == marker
    assert case.prompt_preview == marker
    assert _PNG_BASE64[1000:1064] not in report_html(_report(case))


def test_a_v2_text_message_and_parts_keep_their_order() -> None:
    # INVARIANT: a v2 envelope keeps its string messages as written and its parts in the order
    # the importer wrote them, so the transcript reads like the Case.
    envelope: str = json.dumps(
        {
            "schema": "screamingface.candidate-input.v2",
            "messages": [
                {"role": "system", "content": "Answer with a number."},
                {
                    "role": "user",
                    "content": [
                        _image(f"data:image/png;base64,{_PNG_BASE64}"),
                        _text(_QUESTION),
                    ],
                },
            ],
        }
    )

    assert _case(envelope).conversation == (
        ("system", "Answer with a number."),
        ("user", f"{_PNG_LINE}\n{_QUESTION}"),
    )


_TINY: str = "data:image/png;base64,iVBORw0KGgo="


@pytest.mark.parametrize(
    "value",
    [
        # WHY: the engine reads a non-text schema as a plain prompt, so such a Case runs and its
        # result must render, not crash on an unhashable lookup.
        '{"schema":{"a":1},"messages":[]}',
        '{"schema":[1],"messages":[]}',
        # a part list is a v2 shape; a v1 envelope carrying one is malformed
        _v2(_text("hi"), _image(_TINY), schema="screamingface.candidate-input.v1"),
        _v2(_text("hi"), {"type": "audio", "audio": {"data": "AAAA"}}),
        _v2(_text("hi"), _image("https://example.com/chart.png")),
        _v2(_text("hi"), _image("data:image/png;base64,not base64!")),
        _v2(_text("hi"), _image({"placeholder": "image", "media_type": "image/png", "size": 3})),
        _v2(
            _text("hi"),
            _image(
                {
                    "placeholder": "file",
                    "media_type": "image/png",
                    "size": 3,
                    "sha256": _PNG_SHA256,
                }
            ),
        ),
        _v2(),
    ],
)
def test_an_unknown_or_malformed_envelope_keeps_the_raw_string_fallback(value: str) -> None:
    # INVARIANT: decoding never raises and never fabricates a transcript; anything that is not
    # exactly a known envelope (and not an unknown version of it, above) renders as the raw
    # string, as before OME-1680.
    case = _case(value)

    assert case.conversation is None
    assert case.display_input == value
    assert case.prompt_preview == value
