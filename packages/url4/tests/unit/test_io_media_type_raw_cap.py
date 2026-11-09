"""The 1 KiB Content-Type cap applies to the RAW header, before any strip (``OME-1538``).

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as a node operator I fetch sources from servers I do not control; padding a
Content-Type with whitespace must neither smuggle it past the cap nor make it "absent".
Review of PR #1478 (HupBaHa, 2026-11-02).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.media import bare_media_type, is_text_media_type, require_text

CAP = 1_024


def _refused(content_type: str) -> None:
    # INVARIANT: over the cap is "not one media type" on both paths, whatever it contains.
    assert is_text_media_type(content_type) is False
    with pytest.raises(ResolutionError) as caught:
        bare_media_type("https://x/f", content_type)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


def test_oversized_leading_ows_before_text_plain_is_refused() -> None:
    _refused(" \t" * 5_000 + "text/plain")


def test_oversized_trailing_ows_after_text_plain_is_refused() -> None:
    _refused("text/plain" + "\t " * 5_000)


def test_oversized_all_whitespace_header_is_refused_not_absent() -> None:
    # WHY: an all-OWS value within the cap means "no type" (text); over the cap it is hostile.
    _refused(" " * (CAP + 1))
    _refused("\t" * 1_000_000)


def test_raw_length_at_cap_with_ows_padding_still_parses() -> None:
    padded = " " * (CAP - len("text/plain") - 1) + "text/plain" + "\t"
    assert len(padded) == CAP
    assert is_text_media_type(padded) is True
    assert bare_media_type("https://x/f", padded) == "text/plain"


def test_raw_length_one_over_cap_is_refused_even_if_stripped_value_is_short() -> None:
    padded = " " * (CAP - len("text/plain") + 1) + "text/plain"
    assert len(padded) == CAP + 1
    _refused(padded)


def test_all_whitespace_at_cap_is_still_absent() -> None:
    blank = " " * CAP
    assert is_text_media_type(blank) is True
    assert bare_media_type("https://x/f", blank) is None


class _NoStrip(str):
    """A header whose strip/scan would be a failure: the cap must be decided by length alone."""

    __slots__ = ()

    def strip(self, chars: str | None = None) -> str:
        raise AssertionError("an over-cap header was stripped before the length check")


def test_over_cap_header_is_refused_without_being_stripped() -> None:
    # INVARIANT: an over-cap header is rejected on its raw length; no strip, no scan, no copy.
    _refused(_NoStrip(" " * 10_000 + "text/plain"))
    _refused(_NoStrip(" " * (CAP + 1)))


def test_within_cap_header_is_stripped_normally() -> None:
    # The guard above is not vacuous: a within-cap header does reach strip.
    with pytest.raises(AssertionError, match="stripped"):
        is_text_media_type(_NoStrip(" text/plain"))


class _NoRepr(str):
    """A header whose repr would be a failure: an over-cap diagnostic must not echo it."""

    __slots__ = ()

    def __repr__(self) -> str:
        raise AssertionError("an over-cap header was repr'd into an error message")


def _bare_error(content_type: str) -> ResolutionError:
    with pytest.raises(ResolutionError) as caught:
        bare_media_type("https://x/f", content_type)
    return caught.value


def _text_error(content_type: str) -> ResolutionError:
    with pytest.raises(ResolutionError) as caught:
        require_text("https://x/f", content_type)
    return caught.value


_RaiseFor = Callable[[str], ResolutionError]
_BOTH_PATHS = [_bare_error, _text_error]


@pytest.mark.parametrize("raise_for", _BOTH_PATHS)
def test_over_cap_header_is_never_repr_d_into_the_error(raise_for: _RaiseFor) -> None:
    # INVARIANT: over the cap the diagnostic is length-only (review of PR #1478, HupBaHa).
    error = raise_for(_NoRepr("x" * (CAP + 1)))
    assert error.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert error.permanent is True
    assert f"{CAP + 1} characters, over the {CAP} cap" in str(error)


@pytest.mark.parametrize("raise_for", _BOTH_PATHS)
def test_one_megabyte_header_yields_a_bounded_error_message(raise_for: _RaiseFor) -> None:
    error = raise_for(" " * 500_000 + "image/png" + "\t" * 499_991)
    assert len(str(error)) < 300
    assert "1000000 characters" in str(error)


@pytest.mark.parametrize("raise_for", _BOTH_PATHS)
def test_within_cap_header_is_still_quoted_in_the_error(raise_for: _RaiseFor) -> None:
    # The guard above is not vacuous: a within-cap value keeps today's repr'd message.
    with pytest.raises(AssertionError, match="repr'd"):
        raise_for(_NoRepr("text/"))
