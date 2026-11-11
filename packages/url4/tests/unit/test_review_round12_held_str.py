"""PR #1587 review round 12: a held ``str`` is counted before it is encoded.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as a node operator, two held 7,000,000-character ``[data]`` strings attached in one run
are refused at the 8 MB live cap before the second is encoded: its UTF-8 copy is never
materialized, so the cap bounds what the run holds, not what it produced.
INVARIANT: ``serve_data_bytes`` draws a held str's exact UTF-8 size from the run's budget
(``on_declared``) BEFORE ``str.encode`` builds its body.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest
from url4.peer.server import Url4Node


class _Watched(str):
    """A held body that records each whole-body encode (a slice is a plain ``str``)."""

    encoded: list[int] = []

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        _Watched.encoded.append(len(self))
        return super().encode(encoding, errors)


@pytest.fixture(autouse=True)
def _reset() -> None:
    _Watched.encoded = []


@pytest.mark.asyncio
async def test_the_second_held_body_is_refused_before_it_is_encoded() -> None:
    node = Url4Node("n1", default_processor="/reduce")
    refs = []
    for fill in ("a", "b"):
        text = fill * 7_000_000
        hex_ = hashlib.sha256(text.encode()).hexdigest()
        node.data(f"/blob/sha256/{hex_}", _Watched(text), media_type="image/png")
        refs.append(f"src=/blob/sha256/{hex_}")
    _Watched.encoded = []
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"({refs[0]}, {refs[1]})!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert _Watched.encoded == [7_000_000]  # only the admitted body was ever encoded


@pytest.mark.parametrize("text", ["plain ascii", "naïve café ☕ 𝄞", ""])
@pytest.mark.asyncio
async def test_the_drawn_size_is_the_exact_utf8_length(text: str) -> None:
    node = Url4Node()
    node.data("/t", text)
    drawn: list[int | None] = []
    got = await node.fetch_bytes(FetchRequest("/t", relative=True, on_declared=drawn.append))
    assert got.body == text.encode("utf-8")
    assert drawn == [len(text.encode("utf-8"))]


@pytest.mark.asyncio
async def test_a_refused_held_body_is_never_encoded() -> None:
    node = Url4Node()
    node.data("/t", _Watched("x" * 100))

    def refuse(size: int | None) -> None:
        raise ResolutionError("over", code=ErrorCode.ATTACHMENTS_TOO_LARGE)

    with pytest.raises(ResolutionError):
        await node.fetch_bytes(FetchRequest("/t", relative=True, on_declared=refuse))
    assert _Watched.encoded == []
