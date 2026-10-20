"""The one rule the adapters' text paths share: a binary body is never decoded as text."""

from __future__ import annotations

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import is_text_media_type


def require_text(target: str, content_type: str | None) -> None:
    """Raise ``unsupported_content_type`` (spec C8) when ``content_type`` is binary.

    INVARIANT: every text-returning adapter path calls this BEFORE decoding, so a PNG
    or PDF fails loudly instead of reaching a model as mojibake (``OME-1538``).
    Permanent: a retry gets the same bytes back.
    """
    if not is_text_media_type(content_type):
        raise ResolutionError(
            f"{target!r} is {content_type!r}, which is not text; fetch it as bytes",
            code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            permanent=True,
        )


__all__ = ["require_text"]
