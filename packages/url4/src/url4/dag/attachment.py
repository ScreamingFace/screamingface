"""The typed file attachment a resolved blob ref yields (#1450 spec §2 F2).

FEATURE: image and PDF inputs (epic ``OME-1529``; resolution ``OME-1539``, wiring ``OME-1543``).

INVARIANT (D2): no bytes ride on a ``str``. ``Payload`` stays plain text; a file reaches a
model only as an :class:`Attachment` in the run's ordered ``attachments[]`` side-channel, built
from structure (a ``src=`` file ref in the AST), never by scanning a payload for ref-shaped text.

AIDEV-NOTE: this module is the seam ``OME-1543`` builds on. It owns the run's ordered list
(fixed before execution, D5), the last-user-message placement (D3), and the judge / remote-node
exclusions (D6); none of that lives here. Keep this a plain value: no I/O, no ordering policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OCTET_STREAM = "application/octet-stream"
"""F2 requires a media type; an adapter that reports none gives the generic byte stream."""


@dataclass(frozen=True)
class Attachment:
    """One verified file: the F2 record (``digest``, ``media_type``, ``filename``, ``detail``).

    ``digest`` is ``sha256:<lower-case hex>``. ``body`` is the bytes that hashed to it.
    WHY ``body`` is out of ``repr`` and equality: identity is the verified digest plus the
    F2 metadata (F3), and a log line must never dump a file.
    """

    digest: str
    media_type: str
    body: bytes = field(default=b"", repr=False, compare=False)
    filename: str | None = None
    detail: Literal["auto", "low", "high"] | None = None


__all__ = ["OCTET_STREAM", "Attachment"]
