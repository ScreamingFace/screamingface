"""The Content-Type parser is linear-time and length-capped (``OME-1538``, PR #1478).

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as a node operator I fetch sources from servers I do not control; a crafted
Content-Type header must not stall the node (ReDoS) on the text or the bytes path.
"""

from __future__ import annotations

import time

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.media import bare_media_type, is_text_media_type

PATHOLOGICAL = [
    'text/plain; a="' + '\\"' * 50_000,
    "text/plain" + "  ;  " * 50_000 + ",",
    "text/plain" + ";" * 100_000 + "x",
    "text/plain;" + " " * 100_000 + "\x00",
    "text/plain" + "; a=b" * 50_000 + ",",
    "a" * 100_000 + "/",
]


@pytest.mark.parametrize("content_type", PATHOLOGICAL, ids=range(len(PATHOLOGICAL)))
def test_a_crafted_header_is_refused_in_well_under_100ms(content_type: str) -> None:
    # INVARIANT: parsing is linear-time and capped, so no header can stall a fetch.
    started = time.perf_counter()
    assert is_text_media_type(content_type) is False
    with pytest.raises(ResolutionError):
        bare_media_type("https://x/f", content_type)
    assert time.perf_counter() - started < 0.1


def test_the_backtracking_shape_that_stalled_the_regex_is_fast() -> None:
    # 70 characters took ~11 s through the overlapping `[ \t]*;[ \t]*` regex.
    started = time.perf_counter()
    assert is_text_media_type("text/plain" + "  ;  " * 12 + ",") is False
    assert time.perf_counter() - started < 0.1


def test_a_header_over_one_kib_is_not_one_media_type() -> None:
    padded = 'text/plain; a="' + "x" * 1_010 + '"'
    assert len(padded) > 1_024
    assert is_text_media_type(padded) is False
    with pytest.raises(ResolutionError) as caught:
        bare_media_type("https://x/f", padded)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE


def test_a_header_at_one_kib_still_parses() -> None:
    exact = 'text/plain; a="' + "x" * (1_024 - 16) + '"'
    assert len(exact) == 1_024
    assert is_text_media_type(exact) is True
    assert bare_media_type("https://x/f", exact) == "text/plain"


@pytest.mark.parametrize(
    ("content_type", "text"),
    [
        ('text/plain; a="q\\"uote"', True),
        ('application/vnd.x; a="esc\\\\"; charset=utf-8', True),
        ('application/vnd.x; a="bad\\', False),
        ('application/vnd.x; a="ctl\x01"', False),
        ("application/vnd.x; =v", False),
        ("application/vnd.x; a=", False),
        ("application/vnd.x; a", False),
    ],
)
def test_quoted_pairs_and_malformed_parameters(content_type: str, text: bool) -> None:
    assert is_text_media_type(content_type) is text
