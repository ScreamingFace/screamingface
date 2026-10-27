"""Which ``https://`` sources are attachment sources, their identity, and their classification.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b "Scope of
attachments", review round 7, owner 2026-10-27).
STORY: as an ensemble author I opt a picture in with ``src=https://…/a.png;accept=image/png``;
an ``https://`` source without such an ``;accept=`` stays the text source it always was.

INVARIANT (opt-in, no grammar change): an ``http(s)://`` source is an attachment source iff its
``;accept=`` names only ranges from :data:`ATTACHMENT_RANGES`. No ``;accept=``, or any other
range in it, makes it a text source with today's semantics, untouched.
INVARIANT (identity): ``(URL, accept, ;optional, ;t=, ;retry=)``. Equal identities share one
flight and one attachment; any difference is a separate identity, even for equal bytes.

AIDEV-NOTE: imports only ``core`` so both the lowering (``_descriptor``) and the run-start scan
(``attachments``) can use it without an import cycle; the engine may not import ``io.media``
(``test_import_isolation``), so the bare media type is read here (:func:`_bare_type`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from url4.core._annotations import checked_retries, checked_timeout
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.nodes import Source, Url

ATTACHMENT_RANGES = frozenset(
    {"image/*", "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
)
"""The ``;accept=`` ranges that opt an ``https://`` source in (F1b round 7)."""

ATTACHMENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
)
"""The response media types an attachment source may carry.

WHY concrete types only (conservative reading, ledger round 7): F1b calls the attachment set a
fail-closed subset of the gateway gate; ``image/*`` is a requested *range*, so it matches these
four image types, never an arbitrary ``image/<x>`` such as ``image/svg+xml``.
"""

_WEB_SCHEMES = ("http://", "https://")

GuardPolicy = tuple[bool, float | None, int]
"""``(optional, timeout, retries)`` — the ``;optional`` / ``;t=`` / ``;retry=`` disposition."""


@dataclass(frozen=True)
class AttachmentIdentity:
    """One materialization identity: the URL, the ``;accept=`` as authored, the guard policy."""

    url: str
    accept: str
    optional: bool = False
    timeout: float | None = None
    retries: int = 0

    @property
    def ranges(self) -> tuple[str, ...]:
        return accept_ranges(self.accept)


def accept_ranges(accept: str) -> tuple[str, ...]:
    """The lower-cased media ranges an ``;accept=`` value names (comma-separated)."""
    return tuple(part.strip().lower() for part in accept.split(",") if part.strip())


def is_attachment_accept(accept: str | None) -> bool:
    """Whether ``accept`` names at least one range and only attachment-set ranges."""
    if accept is None:
        return False
    ranges = accept_ranges(accept)
    return bool(ranges) and all(item in ATTACHMENT_RANGES for item in ranges)


def guard_policy(ann: Mapping[str, str | None], node: Source) -> GuardPolicy | None:
    """Decode ``;optional`` / ``;t=`` / ``;retry=`` — None when no guard is needed.

    INVARIANT: the ONE decoding the lowering (``GuardNode``) and the attachment identity share,
    so an occurrence's identity is exactly the policy its guard runs under.
    """
    optional = "optional" in ann
    timeout = _annotation_number(ann.get("t"), "t", float, checked_timeout, node)
    retries = _annotation_number(ann.get("retry"), "retry", int, checked_retries, node)
    if not optional and timeout is None and not retries:
        return None
    return optional, timeout, retries or 0


def _annotation_number(raw: str | None, key: str, cast: Callable, check: Callable, node: Source):
    """Cast and range-check one guard value (the shared rule in ``core._annotations``)."""
    if raw is None:
        return None
    try:
        value = cast(raw)
    except ValueError:
        value = None
    where = node.name or node.value
    try:
        if value is None:
            raise ValueError(f"must be {'an integer' if cast is int else 'a number'}")
        return check(value)
    except ValueError as exc:
        raise ParseError(f"invalid ;{key}={raw!r} on source {where!r}: {exc}") from None


def identity_of(node: Source) -> AttachmentIdentity | None:
    """The attachment identity of a descriptor, or ``None`` for every text source."""
    if not isinstance(node.value, Url) or not node.value.value.startswith(_WEB_SCHEMES):
        return None
    ann = dict(node.annotations)
    accept = ann.get("accept")
    if accept is None or not is_attachment_accept(accept):
        return None
    policy = guard_policy(ann, node) or (False, None, 0)
    return AttachmentIdentity(node.value.value, accept, *policy)


def classify(identity: AttachmentIdentity, content_type: str | None) -> str:
    """The attachment's bare media type, or ``unsupported_content_type`` (permanent, C8).

    INVARIANT (no sniffing): the response's one bare media type must be an attachment type
    AND match a requested range. A missing Content-Type, or one that is not exactly one media
    type, is refused like a wrong one.
    """
    media_type = _bare_type(content_type)
    if media_type is not None and media_type in ATTACHMENT_TYPES:
        if any(_matches(media_type, item) for item in identity.ranges):
            return media_type
    raise ResolutionError(
        f"attachment source {identity.url!r} (;accept={identity.accept}) returned "
        f"Content-Type {content_type!r}, which is not an accepted attachment type",
        code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
        permanent=True,
    )


def _bare_type(content_type: str | None) -> str | None:
    """The lower-cased ``type/subtype`` before any parameter; ``None`` when absent or not one.

    WHY fail-closed on any comma: HTTPX comma-joins duplicate ``Content-Type`` fields, and a
    value that is not exactly one media type must never classify (F1b). A comma inside a
    quoted parameter is refused too; the result must be an exact attachment type anyway.
    """
    if content_type is None or "," in content_type:
        return None
    bare = content_type.split(";", 1)[0].strip(" \t").lower()
    return bare or None


def _matches(media_type: str, wanted: str) -> bool:
    if wanted.endswith("/*"):
        return media_type.startswith(wanted[:-1])
    return media_type == wanted


def not_static(where: str) -> ResolutionError:
    """``x.source_not_static`` (permanent): an attachment target that depends on a model."""
    return ResolutionError(
        f"attachment source {where} is not static: its target depends on a model output, "
        "so it cannot be materialized before the first model call",
        code=ErrorCode.SOURCE_NOT_STATIC,
        permanent=True,
    )


__all__ = [
    "ATTACHMENT_RANGES",
    "ATTACHMENT_TYPES",
    "AttachmentIdentity",
    "GuardPolicy",
    "accept_ranges",
    "classify",
    "guard_policy",
    "identity_of",
    "is_attachment_accept",
    "not_static",
]
