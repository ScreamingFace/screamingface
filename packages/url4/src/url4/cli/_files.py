"""File-backed ``url4 serve`` providers: a file read per request, as text or as its exact bytes.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; local end-to-end run
2026-10-28).
STORY: as an operator I declare ``"/blob/sha256/<hex>" = { file = "cat.png" }`` in ``[data]``,
and the node serves that PNG byte-exact to a file ref, instead of failing with a 500.

File reads happen per request in a worker thread (never on the loop) so operators can edit the
backing file without a restart. A missing/unreadable file is the source's failure, not the
node's: ResolutionError, like a failing command.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import BinaryIO

from url4.core.errors import ErrorCode, ResolutionError


async def _read_file(file: str) -> bytes:
    """The file's exact bytes, read in a worker thread; unreadable is the source's failure."""
    try:
        return await asyncio.to_thread(Path(file).read_bytes)
    except OSError as exc:
        raise ResolutionError(f"data file {file!r} cannot be read: {exc}") from exc


_PIECE = 64 * 1024


async def _read_piece(file: str, handle: BinaryIO) -> bytes:
    try:
        return await asyncio.to_thread(handle.read, _PIECE)
    except OSError as exc:
        raise ResolutionError(f"data file {file!r} cannot be read: {exc}") from exc


def _decoded(file: str, body: bytes) -> str:
    """``body`` as UTF-8 text, or a permanent ``unsupported_content_type`` (spec C8).

    WHY: a binary file (a PNG at ``/blob/sha256/<hex>``) read as text raised a bare
    ``UnicodeDecodeError`` that surfaced as a 500 ``internal_error``; it is the same
    refusal a binary body gets on every text path (``url4.io.media.require_text``).
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResolutionError(
            f"data file {file!r} is not UTF-8 text; fetch it as bytes",
            code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            permanent=True,
        ) from exc


class FileData:
    """A ``[data]`` file route: text for the text path, the exact bytes for the binary path.

    INVARIANT: :meth:`read_bytes` never decodes, so a binary file served at
    ``/blob/sha256/<hex>`` hashes to its digest (``url4.peer._bytes.SupportsReadBytes``).
    """

    def __init__(self, file: str) -> None:
        self._file = file

    async def __call__(self) -> str:
        return await read_text(self._file)

    async def read_bytes(self) -> bytes:
        return await _read_file(self._file)

    async def read_chunks(self) -> AsyncGenerator[bytes]:
        """The file's exact bytes in pieces of at most :data:`_PIECE` (each read off the loop).

        WHY: a run's live byte budget sees each piece as it is read
        (``url4.peer._bytes.SupportsReadChunks``), so a refused blob read stops after about one
        piece instead of loading the whole file (PR #1587 review finding 1).
        """
        try:
            handle = await asyncio.to_thread(open, self._file, "rb")
        except OSError as exc:
            raise ResolutionError(f"data file {self._file!r} cannot be read: {exc}") from exc
        try:
            while piece := await _read_piece(self._file, handle):
                yield piece
        finally:
            handle.close()


async def read_text(file: str) -> str:
    """The file decoded as UTF-8 text (the text path of every file provider)."""
    return _decoded(file, await _read_file(file))


__all__ = ["FileData", "read_text"]
