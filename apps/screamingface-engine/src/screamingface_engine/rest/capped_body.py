"""Read a request body up to a byte cap. Shared by the blob upload and `POST /runs`.

INVARIANT: a body over the cap is refused as soon as it is known to be over it, from its declared
length or while it streams, so a caller never makes the App hold more than the cap.
"""

from __future__ import annotations

from fastapi import Request


class BodyTooLarge(ValueError):
    """The body is longer than the cap."""


async def capped_body(request: Request, max_bytes: int) -> bytes:
    """The whole body of ``request``, at most ``max_bytes`` long.

    Raises:
        BodyTooLarge: the body declares, or streams, more than ``max_bytes``.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise BodyTooLarge(f"the body exceeds the {max_bytes}-byte cap")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise BodyTooLarge(f"the body exceeds the {max_bytes}-byte cap")
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["BodyTooLarge", "capped_body"]
