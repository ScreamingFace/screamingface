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
