"""Engine-side twin of the SDK's placeholder conformance bind (OME-1679).

FEATURE: the engine writes a placeholder where a picture's bytes were (OME-1679) and the SDK's
Case Result reads it (OME-1680). STORY: as a researcher, a field renamed on one side cannot leave
my results showing a raw object instead of ``chart.png · image/png · 300 KB``.
WHY a twin: CI is path-filtered, so the SDK's copy of this test never runs on an engine-only PR.
This one runs in the ENGINE lane and parses the SDK's source; no cross-app import either way.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NotRequired, get_origin, get_type_hints

import pytest

from screamingface_engine.benchmarks.candidate_input import MediaPlaceholder, media_placeholder

# parents[3] = apps/, so its parent is the monorepo root
_SDK_PACKAGE = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"
_SDK_CASE_RESULT = _SDK_PACKAGE / "src" / "screamingface" / "case_result.py"


def _sdk_name_set(name: str) -> set[str]:
    """The strings in ``name = frozenset({...})`` at the top of the SDK's ``case_result.py``."""

    for node in ast.parse(_SDK_CASE_RESULT.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.args[0], ast.Set)
        ):
            return {
                element.value
                for element in node.value.args[0].elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError(f"{name} = frozenset({{...}}) not found in {_SDK_CASE_RESULT}")


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_engine_placeholder_fields_are_the_sdks() -> None:
    # INVARIANT: one placeholder shape on both sides. A present SDK package with a moved file must
    # FAIL, not skip.
    assert _SDK_CASE_RESULT.exists(), "SDK case_result.py moved — update the bind"
    # WHY resolved hints, not __required_keys__: the module's postponed annotations hide
    # NotRequired from the TypedDict's own key sets.
    hints: dict[str, object] = get_type_hints(MediaPlaceholder, include_extras=True)
    optional: set[str] = {name for name, hint in hints.items() if get_origin(hint) is NotRequired}

    assert set(hints) - optional == _sdk_name_set("_PLACEHOLDER_FIELDS")
    assert optional == _sdk_name_set("_PLACEHOLDER_OPTIONAL_FIELDS")


def test_the_engine_measures_the_picture_the_sdk_pins() -> None:
    # WHY one literal on both sides: field names alone would let one side hash the base64 text
    # and the other the bytes. The SDK's twin pins this same picture to this same placeholder.
    assert media_placeholder(
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        where="message 0 part 0",
    ) == {
        "placeholder": "image",
        "media_type": "image/png",
        "size": 8,
        "sha256": "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6",
    }
