"""A sticky byte-cap refusal always wins over a concurrent sibling's source error.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 6,
owner decision Sergey 2026-11-04).
STORY: as a node operator, a run whose attachments passed the 8,000,000-byte cap is refused
``x.attachments_too_large`` every time — never ``source_not_found`` one run and the cap the next,
depending on which concurrent flight's failure the task group happened to see first.

The io is deterministic: the breaching flight holds its refusal until the sibling has failed, which
is exactly the ordering that let ``gather_or_cancel``'s first-leaf pick surface the sibling.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._caps import MAX_ATTACHMENT_BYTES
from url4.dag._run import run
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

BIG = "https://files.example/big.png"
GONE = "https://files.example/gone.png"


class _Racing(StaticIOLayer):
    """``BIG`` breaches the live budget, then waits for ``GONE`` to fail before it re-raises."""

    def __init__(self, gone_code: str = ErrorCode.SOURCE_NOT_FOUND) -> None:
        super().__init__({})
        self.gone_code = gone_code
        self.breached = asyncio.Event()
        self.gone_failed = asyncio.Event()

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        if request.target == BIG:
            try:
                assert request.on_chunk is not None
                request.on_chunk(MAX_ATTACHMENT_BYTES + 1)
            except ResolutionError:
                self.breached.set()
                await self.gone_failed.wait()  # cancelled here once GONE fails
                raise
            raise AssertionError("the budget did not refuse")
        await self.breached.wait()
        try:
            raise ResolutionError("gone", code=self.gone_code, permanent=True)
        finally:
            self.gone_failed.set()


async def _never(sources: str, intent: str | None, scope: object) -> str:
    raise AssertionError("no model call after a cap refusal")


@pytest.mark.asyncio
@pytest.mark.parametrize("gone_code", [ErrorCode.SOURCE_NOT_FOUND, ErrorCode.RESOLUTION_FAILED])
async def test_a_sibling_failing_after_the_breach_does_not_mask_the_cap_refusal(
    gone_code: str,
) -> None:
    io = _Racing(gone_code)
    text = f"(src={BIG};accept=image/png, src={GONE};accept=image/png)!'d'"
    with pytest.raises(ResolutionError) as caught:
        await asyncio.wait_for(run(text, io, process=_never), 10)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert caught.value.permanent is True


@pytest.mark.asyncio
async def test_the_cap_wins_whatever_the_source_order() -> None:
    io = _Racing()
    text = f"(src={GONE};accept=image/png, src={BIG};accept=image/png)!'d'"
    with pytest.raises(ResolutionError) as caught:
        await asyncio.wait_for(run(text, io, process=_never), 10)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE


@pytest.mark.asyncio
async def test_a_source_error_with_no_breach_still_surfaces_as_itself() -> None:
    class _Gone(StaticIOLayer):
        async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
            raise ResolutionError("gone", code=ErrorCode.SOURCE_NOT_FOUND, permanent=True)

    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={GONE};accept=image/png)!'d'", _Gone({}), process=_never)
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND
