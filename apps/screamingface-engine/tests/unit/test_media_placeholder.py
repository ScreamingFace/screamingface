"""The placeholder that stands in for a picture's or file's bytes (OME-1679).

FEATURE: a Fusion's synthesizer reads the Case as text beside the pictures it is sent; each
picture in that text is this placeholder, never its base64. STORY: as a researcher running a
Fusion on MMMU, the synthesizer reads a few hundred characters per picture, not a megabyte.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    FilePart,
    ImagePart,
    media_placeholder,
)

# The 8-byte PNG signature, as base64. WHY these bytes: small enough to check by hand, and the
# SDK's conformance test pins the same literal, so both sides measure one picture the same way.
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PNG_SHA256 = "4c4b6a3be1314ab86138bef4314dde022e600960d8689a2c8f8631802d20dab6"


def _image(url: str) -> ImagePart:
    """A picture part as the envelope reader returns it."""

    return {"type": "image_url", "image_url": {"url": url}}


def test_a_picture_is_named_by_its_decoded_bytes() -> None:
    # INVARIANT: size and sha256 are the picture's bytes, not its base64 text, so the number a
    # researcher sees is the file they put in the Case.
    assert media_placeholder(_image(_PNG), where="message 0 part 1") == {
        "placeholder": "image",
        "media_type": "image/png",
        "size": 8,
        "sha256": _PNG_SHA256,
    }


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,iVBORw0K\nGgo=",
        "data:image/png;base64,iVBORw0KGgo",
        "data:IMAGE/PNG;base64,iVBORw0KGgo=",
    ],
    ids=["wrapped onto lines", "padding dropped", "upper-case type"],
)
def test_one_picture_spelled_another_way_gets_one_placeholder(url: str) -> None:
    # WHY: the gateway and every provider read these as the same picture, so the placeholder does.
    placeholder = media_placeholder(_image(url), where="message 0 part 1")

    assert (placeholder["media_type"], placeholder["sha256"]) == ("image/png", _PNG_SHA256)


def test_a_file_placeholder_carries_its_filename() -> None:
    part: FilePart = {
        "type": "file",
        "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQ=", "filename": "paper.pdf"},
    }

    assert media_placeholder(part, where="message 0 part 0") == {
        "placeholder": "file",
        "media_type": "application/pdf",
        "size": 8,
        # The sha256 of b"%PDF-1.4", the 8 bytes this base64 spells.
        "sha256": "e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e",
        "filename": "paper.pdf",
    }


def test_a_picture_that_is_not_base64_is_refused_by_place() -> None:
    # WHY refuse rather than guess: a placeholder must describe real bytes, and the provider
    # rejects this picture anyway. The refusal never repeats the payload.
    with pytest.raises(
        CandidateInputError, match="message 0 part 1: the image is not valid base64"
    ):
        media_placeholder(
            _image("data:image/png;base64,***not-base64***"), where="message 0 part 1"
        )


def test_a_picture_that_is_not_inline_is_refused_by_place() -> None:
    # WHY a named refusal, not an assert: the builder is public, so a hand-built part can reach
    # it without the envelope reader's check, and an assert vanishes under ``python -O``.
    with pytest.raises(CandidateInputError, match="message 0 part 1: expected an inline data: URI"):
        media_placeholder(_image("https://insecure-website.com/a.png"), where="message 0 part 1")
