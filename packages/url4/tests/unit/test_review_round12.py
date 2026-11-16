"""PR #1587 self-review before round 12: a text-only io never holds a blob past the live cap.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as a node operator whose io adapter has no ``fetch_bytes`` (text only), two 7 MB
``/blob/sha256/<hex>`` attachments are refused ``x.attachments_too_large`` with ZERO reads —
not after both bodies were held (14 MB against the 8,000,000-byte budget).
INVARIANT (decision B, round 11 finding 1): under a run's live cap a body is counted BEFORE it
is held. The text fallback can only count after its read, so it is refused unread, exactly as
``peer._bytes`` refuses a whole-body provider.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.io.layer import FetchRequest, FetchResult

A = "a" * 7_000_000
B = "b" * 7_000_000
_BODIES = {hashlib.sha256(x.encode()).hexdigest(): x for x in (A, B)}


class _TextOnly:
    """An io with ``fetch``/``fetch_ex`` only; every body read is recorded."""

    def __init__(self) -> None:
        self.reads: list[int] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        return self._get(target)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        return FetchResult(self._get(request.target), media_type="image/png")

    def _get(self, target: str) -> str:
        body = _BODIES[target.rsplit("/", 1)[-1]]
        self.reads.append(len(body))
        return body

    def has_code(self, path: str) -> bool:
        return True

    async def invoke_code(self, call: object) -> str:
        return "ok"


async def _model(sources: object, intent: object, scope: object) -> str:
    return "ok"


@pytest.mark.asyncio
async def test_a_text_only_io_blob_attachment_is_refused_unread_under_the_live_cap() -> None:
    io = _TextOnly()
    ha, hb = list(_BODIES)
    with pytest.raises(ResolutionError) as exc:
        await asyncio.wait_for(
            run(f"(src=/blob/sha256/{ha}, src=/blob/sha256/{hb}, 'q')!'d'", io, process=_model),
            10,
        )
    assert exc.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert io.reads == []
