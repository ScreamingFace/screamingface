"""A Form-3 processor expression that names a file is refused at run start, before any I/O.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY (PR #1587 pre-review, round 13): as an ensemble author, a ``processor=`` expression that
names an attachment source or an attached blob ref fails ``x.source_not_static`` before the run
pays for any member call. Without this, the run fetched every member and failed only when the
processor resolved, or read the blob uncapped and attached nothing.
INVARIANT: the processor's files are never admitted into the run's manifest (fail closed); a
text-only Form-3 processor runs as before.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.dag._run import run
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes

PNG = b"\x89PNG\r\n\x1a\n-form3"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
TARGET = "(/m('a')!'member')!'d'"


class _Recording:
    """An io that records every call on every port."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return '["r"]'

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult('["r"]')

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(PNG, "image/png")


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.calls += 1
        return "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "processor",
    [
        pytest.param("(src=https://f.example/p.png;accept=image/png)!'t'", id="https-source"),
        pytest.param("(src=$x;accept=image/png)!'t'", id="non-literal-source"),
        pytest.param(f"(src=/blob/sha256/{PNG_HEX})!'t'", id="blob-ref"),
        pytest.param(f"(/blob/sha256/{PNG_HEX}, 'q')!'t'", id="bare-blob-ref"),
    ],
)
async def test_a_form3_processor_naming_a_file_is_refused_before_any_io(processor: str) -> None:
    io, model = _Recording(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(TARGET, io, processor=processor, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert io.calls == []
    assert model.calls == 0


@pytest.mark.asyncio
async def test_a_text_only_form3_processor_is_not_refused_at_run_start() -> None:
    io, model = _Recording(), _Model()
    try:
        await run(TARGET, io, processor="('x', 'q')!'t'", process=model)
    except Url4Error as error:
        # WHY: the stub model's "ok" is no processor id; only a run-start refusal matters here.
        assert error.code != ErrorCode.SOURCE_NOT_STATIC
    assert io.calls  # the member ran: nothing refused the text-only processor up front
