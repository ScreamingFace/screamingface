"""OME-1044 — the shared canonical digest every cache lane hashes through.

FEATURE: one canonical form for every cache key in this app, so two lanes can never
disagree about what a given request keys to.

INVARIANT under test: the BYTES, not merely the behaviour. A second spelling of the
canonical form is how the out-of-repo DRACO backfill silently mis-keyed every row it
wrote — it escaped U+2028 where the gateway did not — so these tests pin the exact
form rather than "it returns a hash".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest

from aigateway.core.request_cache import canonical
from aigateway.core.request_cache.canonical import CanonicalizationError, canonical_digest


def _house_form(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _with_non_string_key() -> Mapping[str, Any]:
    """A mapping whose key is an ``int`` at RUNTIME, declared as the annotated type.

    WHY the declared type and the runtime value disagree on purpose: this guard exists for
    data whose static type is a promise nobody checked — a parsed JSON body, or a provider
    projection hook returning ordinary Python. Constructing it this way reproduces exactly
    that situation without suppressing the type checker.
    """
    bad: dict[Any, Any] = {1: "a"}
    return bad


def test_the_digest_is_the_sha256_of_the_house_canonical_form() -> None:
    mapping = {"b": 2, "a": 1}
    expected = hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    assert canonical_digest(mapping) == expected
    assert len(canonical_digest(mapping)) == 64


def test_object_key_order_does_not_change_the_digest() -> None:
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})


def test_array_order_does_change_the_digest() -> None:
    # WHY: arrays carry ordered data. An exclusion list is sorted by its OWNER before it
    # reaches here, so order-insensitivity must NOT be smuggled in at this layer.
    assert canonical_digest({"x": [1, 2]}) != canonical_digest({"x": [2, 1]})


def test_non_ascii_text_is_hashed_raw_rather_than_escaped() -> None:
    # INVARIANT: `ensure_ascii=False`. This is the U+2028 regression in test form: under
    # the stdlib default that one character becomes six literal characters, the digest
    # moves, and a second module keying the same request never finds the same row.
    body = {"q": "line-a\u2028line-b"}  # U+2028: an escape, since it is invisible raw
    assert canonical_digest(body) == hashlib.sha256(_house_form(body).encode("utf-8")).hexdigest()
    assert (
        canonical_digest(body)
        != hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    )


def test_a_non_string_object_key_is_refused_rather_than_coerced() -> None:
    # INVARIANT: `json.dumps` COERCES {1: "a"} to {"1": "a"}, so two genuinely different
    # mappings would collapse onto one entry. A WRONG hit is the single failure mode a
    # shared cache may never have, so the ambiguous input is refused instead.
    assert json.dumps({1: "a"}) == json.dumps({"1": "a"})
    with pytest.raises(CanonicalizationError):
        canonical_digest(_with_non_string_key())


def test_a_non_finite_number_is_refused() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_digest({"x": float("inf")})
    with pytest.raises(CanonicalizationError):
        canonical_digest({"x": float("nan")})


def test_an_unsupported_type_is_refused_and_the_message_names_only_the_type() -> None:
    with pytest.raises(CanonicalizationError) as excinfo:
        canonical_digest({"x": {"a", "b"}})
    message = str(excinfo.value)
    # INVARIANT: the type NAME only — the value could be caller text or a secret.
    assert "set" in message
    assert "'a'" not in message
    assert "'b'" not in message


def test_nesting_beyond_the_cap_is_refused() -> None:
    deep: object = "leaf"
    for _ in range(80):
        deep = {"n": deep}
    with pytest.raises(CanonicalizationError):
        canonical_digest({"x": deep})


def test_every_exported_entry_point_applies_the_json_safety_guard() -> None:
    # INVARIANT: there is NO public way to reach the formatter without the guard. The
    # surface is pinned so that adding an unguarded shortcut fails here, which is the
    # property that matters — not the exact number of exports.
    assert set(canonical.__all__) == {
        "CanonicalizationError",
        "canonical_digest",
        "canonical_material",
    }
    for entry_point in (canonical.canonical_digest, canonical.canonical_material):
        with pytest.raises(CanonicalizationError):
            entry_point(_with_non_string_key())


def test_the_material_is_the_digests_preimage() -> None:
    # WHY both are exported: the chat lane's public `canonical_key_material` returns the
    # STRING (pinned byte-for-byte by its own tests), while every lane keys off the
    # digest. They must not drift, so the digest is defined as the hash of the material.
    mapping = {"a": 1, "b": [2, 3]}
    material = canonical.canonical_material(mapping)
    assert canonical_digest(mapping) == hashlib.sha256(material.encode("utf-8")).hexdigest()
