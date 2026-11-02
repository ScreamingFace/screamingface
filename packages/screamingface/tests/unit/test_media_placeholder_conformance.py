"""The SDK reads exactly the placeholder the engine writes (OME-1679).

FEATURE: a Case Result shows a picture as ``chart.png · image/png · 300 KB`` (OME-1680), from the
placeholder the engine writes where the picture's bytes were (OME-1679). STORY: as a researcher,
a field renamed on one side cannot leave my results showing a raw object instead.
The engine lane runs the twin (apps/screamingface-engine/tests/unit/
test_media_placeholder_conformance.py), so whichever side drifts goes red in its own lane.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface.case_result import (
    _PLACEHOLDER_FIELDS,
    _PLACEHOLDER_OPTIONAL_FIELDS,
    CaseGrade,
    CaseResult,
    _decoded_placeholder,
)

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_ENVELOPE = (
    _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "candidate_input.py"
)


def _engine_placeholder_fields() -> tuple[set[str], set[str]]:
    """The required and optional keys of the engine's ``MediaPlaceholder`` TypedDict."""

    for node in ast.parse(_ENGINE_ENVELOPE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == "MediaPlaceholder":
            fields: list[ast.AnnAssign] = [
                item
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            ]
            optional: set[str] = {
                field.target.id
                for field in fields
                if isinstance(field.target, ast.Name)
                and isinstance(field.annotation, ast.Subscript)
                and isinstance(field.annotation.value, ast.Name)
                and field.annotation.value.id == "NotRequired"
            }
            names: set[str] = {
                field.target.id for field in fields if isinstance(field.target, ast.Name)
            }
            return names - optional, optional
    raise AssertionError(f"class MediaPlaceholder not found in {_ENGINE_ENVELOPE}")


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_sdk_placeholder_fields_are_the_engines() -> None:
    # INVARIANT: one placeholder shape on both sides. Parsed from source because an app's
    # internals may never be imported; a present app with a moved file must FAIL, not skip.
    assert _ENGINE_ENVELOPE.exists(), "engine candidate_input.py moved — update the bind"
    required, optional = _engine_placeholder_fields()

    # WHY a floor: a parse that finds nothing would make the equality vacuous.
    assert "sha256" in required
    assert (set(_PLACEHOLDER_FIELDS), set(_PLACEHOLDER_OPTIONAL_FIELDS)) == (required, optional)


def test_the_sdk_measures_the_picture_the_engine_pins() -> None:
    # WHY one literal on both sides: field names alone would let one side hash the base64 text
    # and the other the bytes. The engine's twin pins this same picture to this same placeholder.
    assert _decoded_placeholder("image", "data:image/png;base64,iVBORw0KGgo=") == {
        "placeholder": "image",
        "media_type": "image/png",
        "size": 8,
        "sha256": "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6",
    }


# The engine's echo of a one-picture v2 Case, byte for byte as its twin pins it
# (apps/screamingface-engine/tests/unit/test_echoed_input.py, OME-1271).
_ENGINE_ECHO = (
    '{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":'
    '[{"type":"image_url","image_url":{"url":{"placeholder":"image","media_type":"image/png",'
    '"size":8,"sha256":"4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6"'
    "}}}]}]}"
)
# The same echo for a named PDF: the engine's placeholder carries the filename, and the part
# keeps its own beside it.
_ENGINE_FILE_ECHO = (
    '{"schema":"screamingface.candidate-input.v2","messages":[{"role":"user","content":'
    '[{"type":"file","file":{"file_data":{"placeholder":"file","media_type":"application/pdf",'
    '"size":8,"sha256":"e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e",'
    '"filename":"paper.pdf"},"filename":"paper.pdf"}}]}]}'
)


def _echoed_case(value: str) -> CaseResult:
    """A scored Case Result whose input is ``value``, as the engine published it."""

    return CaseResult(
        case_id=1,
        input=value,
        output="a bar chart",
        finish_reason="stop",
        grade=CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )


def test_the_sdk_reads_the_engines_echoed_picture_as_its_placeholder_line() -> None:
    # INVARIANT (OME-1271): a Case Result whose input the engine echoed with placeholders reads
    # as the picture's line, not as the raw object; a drift on either side fails this literal.
    assert _echoed_case(_ENGINE_ECHO).conversation == (
        ("user", "image/png · 8 B · sha256 4c4b6a3b…"),
    )
    assert _echoed_case(_ENGINE_FILE_ECHO).conversation == (
        ("user", "paper.pdf · application/pdf · 8 B · sha256 e16fa5d9…"),
    )
