"""`canonical_compose`: splicing canonical member texts equals one `canonical_material` call.

FEATURE: OME-1307 (E14) - the archive writer composes each line and each blob digest from member
texts that are canonical already, so a large body is never parsed and walked again.
INVARIANT: `canonical_compose` is INTERNAL. It is NOT in ``canonical.__all__`` (the pin in
``test_canonical_digest.py`` stays as it is), so it is imported from the module by name.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aigateway.core.request_cache import canonical
from aigateway.core.request_cache.canonical import (
    CanonicalizationError,
    canonical_compose,
    canonical_material,
)

_TEXT = st.text(alphabet=st.characters(codec="utf-8"))
_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63)
    | st.floats(allow_nan=False, allow_infinity=False)
    | _TEXT,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_TEXT, children, max_size=4),
    max_leaves=12,
)
_OBJECT = st.dictionaries(_TEXT, _JSON, max_size=5)


def test_compose_is_not_part_of_the_public_surface() -> None:
    assert "canonical_compose" not in canonical.__all__


@settings(max_examples=150, deadline=None)
@given(values=_OBJECT, members=_OBJECT)
def test_compose_equals_canonical_material_of_the_merged_mapping(
    values: dict[str, Any], members: dict[str, Any]
) -> None:
    members = {k: v for k, v in members.items() if k not in values}
    rendered = {key: canonical_material(member) for key, member in members.items()}

    assert canonical_compose(values, rendered) == canonical_material({**values, **members})


@settings(max_examples=150, deadline=None)
@given(value=_JSON)
def test_canonical_material_is_a_fixed_point_of_parse_and_render(value: Any) -> None:
    # WHY this matters: a stored canonical text may be spliced as is only because parsing it and
    # rendering it again gives the same bytes. Floats, non-ASCII text, U+2028 and escapes included.
    material = canonical_material(value)

    assert canonical_material(json.loads(material)) == material


def test_compose_of_nothing_is_an_empty_object() -> None:
    assert canonical_compose({}, {}) == canonical_material({}) == "{}"


def test_compose_sorts_by_code_point_and_escapes_keys_like_the_formatter() -> None:
    values = {"é": 1, "E": 2, 'q"\\': 3}
    rendered = {"e": "[1]", " ": "null", "\x01": '"x"'}

    expected = canonical_material({**values, **{k: json.loads(t) for k, t in rendered.items()}})

    assert canonical_compose(values, rendered) == expected


def test_compose_refuses_a_key_in_both_mappings() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_compose({"a": 1}, {"a": "2"})


def test_compose_refuses_a_non_string_key_in_either_mapping() -> None:
    bad: Any = {1: "2"}
    with pytest.raises(CanonicalizationError):
        canonical_compose({}, bad)
    with pytest.raises(CanonicalizationError):
        canonical_compose(bad, {})


@pytest.mark.parametrize(
    "unsafe",
    [float("nan"), float("inf"), object(), {"k": {1: "a"}}, {"k": [b"bytes"]}],
)
def test_compose_guards_the_values(unsafe: Any) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_compose({"v": unsafe}, {"r": "1"})


def test_compose_guards_the_depth_of_the_values() -> None:
    deep: Any = {}
    for _ in range(80):
        deep = {"n": deep}

    with pytest.raises(CanonicalizationError):
        canonical_compose({"v": deep}, {})
