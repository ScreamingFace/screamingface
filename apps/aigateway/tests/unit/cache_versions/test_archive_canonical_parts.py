"""The archive writers equal the pre-E14-25 algorithm, byte for byte, in every input form.

FEATURE: OME-1307 (E14) - the writers now splice canonical texts instead of walking and dumping each
value again. The bytes (and so every recorded ``archive_sha256``) must not change.
INVARIANT: ``_reference_*`` below is a FROZEN COPY of the algorithm before the change. Do not
"improve" it: it is the oracle, and a golden literal pins it against the oracle drifting too.
"""

from __future__ import annotations

import gzip
import hashlib
import io
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aigateway.core.cache_versions.archive import (
    ArchiveDigest,
    CanonicalEntry,
    _archive_line,
    _as_canonical,
    blob_digest,
    blob_sha256,
    write_canonical,
    write_entries,
)
from aigateway.core.cache_versions.ports import ArchiveEntry, CanonicalJson
from aigateway.core.request_cache.canonical import (
    CanonicalizationError,
    canonical_digest,
    canonical_material,
)

# --- the frozen reference: today's algorithm, copied ----------------------------------------------


def _reference_write(entries: list[ArchiveEntry]) -> tuple[bytes, ArchiveDigest]:
    buffer = io.BytesIO()
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0)
    try:
        for entry in sorted(entries, key=lambda e: (e.first_ordinal, e.key_hash)):
            line = canonical_material(
                {
                    "key_hash": entry.key_hash,
                    "first_ordinal": entry.first_ordinal,
                    "request": entry.request,
                    "response": entry.response,
                    "metadata": entry.metadata,
                }
            )
            gz.write(f"{line}\n".encode())
    finally:
        gz.close()
    data = buffer.getvalue()
    return data, ArchiveDigest(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))


def _reference_blob_sha256(request: Any, response: Any) -> str:
    return canonical_digest({"request": request, "response": response})


# --- strategies and the three input forms ---------------------------------------------------------

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
# The same, with the non-finite floats the guard refuses, to check the failure parity.
_JSON_MAYBE_BAD = st.recursive(
    st.none() | st.floats() | _TEXT,
    lambda children: st.lists(children, max_size=3) | st.dictionaries(_TEXT, children, max_size=3),
    max_leaves=8,
)


def _entries(values: st.SearchStrategy[Any]) -> st.SearchStrategy[list[ArchiveEntry]]:
    return st.lists(
        st.builds(
            ArchiveEntry,
            key_hash=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
            first_ordinal=st.integers(min_value=0, max_value=10_000),
            request=values,
            response=values,
            metadata=st.none() | values,
        ),
        max_size=6,
    )


def _as_canonical_json_form(entries: list[ArchiveEntry]) -> list[ArchiveEntry]:
    def wrap(value: Any) -> CanonicalJson:
        return CanonicalJson(canonical_material(value))

    return [
        ArchiveEntry(
            e.key_hash,
            e.first_ordinal,
            wrap(e.request),
            wrap(e.response),
            None if e.metadata is None else wrap(e.metadata),
        )
        for e in entries
    ]


def _as_texts(entries: list[ArchiveEntry]) -> list[CanonicalEntry]:
    return [
        CanonicalEntry(
            e.key_hash,
            e.first_ordinal,
            canonical_material(e.request),
            canonical_material(e.response),
            None if e.metadata is None else canonical_material(e.metadata),
        )
        for e in entries
    ]


def _write(write: Any, entries: Any) -> tuple[bytes, ArchiveDigest]:
    buffer = io.BytesIO()
    digest = write(entries, buffer, max_bytes=10**9)
    return buffer.getvalue(), digest


# --- equality with the reference ------------------------------------------------------------------


@settings(max_examples=80, deadline=None)
@given(entries=_entries(_JSON))
def test_every_writer_form_gives_the_reference_bytes(entries: list[ArchiveEntry]) -> None:
    expected_bytes, expected = _reference_write(entries)

    for write, given_entries in (
        (write_entries, entries),
        (write_entries, _as_canonical_json_form(entries)),
        (write_canonical, _as_texts(entries)),
    ):
        data, digest = _write(write, given_entries)
        assert data == expected_bytes
        assert digest == expected


@settings(max_examples=80, deadline=None)
@given(entries=_entries(_JSON_MAYBE_BAD))
def test_a_value_the_guard_refuses_still_raises_and_all_else_matches(
    entries: list[ArchiveEntry],
) -> None:
    try:
        expected_bytes, expected = _reference_write(entries)
    except CanonicalizationError:
        with pytest.raises(CanonicalizationError):
            write_entries(entries, None, max_bytes=10**9)
        return
    data, digest = _write(write_entries, entries)
    assert (data, digest) == (expected_bytes, expected)


@settings(max_examples=60, deadline=None)
@given(value_a=_JSON, value_b=_JSON)
def test_blob_digest_and_blob_sha256_equal_the_canonical_digest(value_a: Any, value_b: Any) -> None:
    expected = _reference_blob_sha256(value_a, value_b)

    assert blob_sha256(value_a, value_b) == expected
    assert (
        blob_sha256(
            CanonicalJson(canonical_material(value_a)), CanonicalJson(canonical_material(value_b))
        )
        == expected
    )
    assert blob_digest(canonical_material(value_a), canonical_material(value_b)) == expected


@settings(max_examples=60, deadline=None)
@given(entries=_entries(_JSON))
def test_archive_line_and_as_canonical_give_the_reference_line(
    entries: list[ArchiveEntry],
) -> None:
    for entry in entries:
        expected = canonical_material(
            {
                "key_hash": entry.key_hash,
                "first_ordinal": entry.first_ordinal,
                "request": entry.request,
                "response": entry.response,
                "metadata": entry.metadata,
            }
        )
        assert _archive_line(_as_canonical(entry)) == expected


# --- the golden literal, recorded on the code BEFORE the change -----------------------------------


def _golden_entries() -> list[ArchiveEntry]:
    # Non-ASCII, U+2028/U+2029, control characters, quotes, backslashes, -0.0, 1e16, a metadata of
    # None, an empty metadata, a top-level list value and an out-of-order input.
    return [
        ArchiveEntry(
            "b" * 64,
            3,
            {
                "model": "mé",
                "messages": [
                    {
                        "role": "user",
                        "content": "café ☃ \U0001f600     tab\there \x01\x1f"
                        ' "q" back\\slash </script>',
                    }
                ],
                "temperature": -0.0,
                "big": 1e16,
                "n": 2**63,
            },
            {
                "choices": [{"message": {"content": "line1\nline2\r\nü"}}],
                "usage": {"x": 1.5, "y": 1e-07},
            },
            None,
        ),
        ArchiveEntry(
            "a" * 64,
            1,
            ["top", ["level", {"z": None, "a": [True, False, 0.1, 123456789.123456789]}], " "],
            {"z": "é", "a": {"é": 1, "e": 2, "E": 3}},
            {"who": "Mé", "n": [1, 2.0, -0.0], "q": '"\\'},
        ),
        ArchiveEntry(
            "c" * 64,
            2,
            {"k": "\u0000\u007f\u0080퟿￿"},
            ["resp", 1e16, -0.0, 1e22, 5e-324],
            {},
        ),
    ]


# Recorded by running the UNCHANGED `write_entries` and `blob_sha256` over `_golden_entries()`.
_GOLDEN_UNCOMPRESSED_SHA256 = "13e394910848f39299dfe85514d326b690e4930b8d85954696526d22f71d86b8"
_GOLDEN_BLOB_SHAS = {
    "b": "500a65cd7eecc2be45120305d5d20e83d5851fcf101403fee546a8660b1ec410",
    "a": "a22c7a189493b8d714ba280ed936d1fb8f5501dbf910a90e94cf6a15fc9e4b95",
    "c": "b1a3c505f21cc88642655b5469b54e306a820f10038152a7cd65fcdd7048167e",
}


def test_the_golden_archive_digest_has_not_moved_in_any_form() -> None:
    entries = _golden_entries()
    forms = (
        (write_entries, entries),
        (write_entries, _as_canonical_json_form(entries)),
        (write_canonical, _as_texts(entries)),
    )
    for write, given_entries in forms:
        data, digest = _write(write, given_entries)
        # Only the UNCOMPRESSED lines are pinned: the gzip bytes depend on the zlib build.
        assert hashlib.sha256(gzip.decompress(data)).hexdigest() == _GOLDEN_UNCOMPRESSED_SHA256
        assert digest == _reference_write(entries)[1]


def test_the_golden_blob_digests_have_not_moved_in_any_form() -> None:
    for entry in _golden_entries():
        golden = _GOLDEN_BLOB_SHAS[entry.key_hash[0]]
        assert blob_sha256(entry.request, entry.response) == golden
        assert (
            blob_digest(canonical_material(entry.request), canonical_material(entry.response))
            == golden
        )


# --- the new types --------------------------------------------------------------------------------


def test_canonical_json_is_not_a_string_and_canonical_material_refuses_it() -> None:
    wrapped = CanonicalJson('{"a":1}')

    assert not isinstance(wrapped, str)
    with pytest.raises(CanonicalizationError):
        canonical_material(wrapped)  # type: ignore[arg-type]
    with pytest.raises(CanonicalizationError):
        canonical_material({"request": wrapped})


def test_neither_new_type_shows_its_text_in_a_repr() -> None:
    secret = "SECRET-PROMPT-TEXT"
    wrapped = CanonicalJson(f'"{secret}"')
    entry = CanonicalEntry("a" * 64, 0, f'"{secret}"', f'"{secret}"', f'"{secret}"')

    assert secret not in repr(wrapped)
    assert secret not in repr(entry)
    assert secret not in str(entry)
    assert repr(wrapped) == f"CanonicalJson(<{len(wrapped.text)} chars>)"


def test_write_canonical_sorts_before_rendering_and_ignores_input_order() -> None:
    entries = _as_texts(_golden_entries())

    forward = _write(write_canonical, entries)
    backward = _write(write_canonical, list(reversed(entries)))

    assert forward == backward
