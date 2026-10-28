"""Which ``https://`` sources are attachment sources, their identity, and their classification.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b "Scope of
attachments", review rounds 7 and 8, owner 2026-10-27).
STORY: as an ensemble author I opt a picture in with ``src=https://…/a.png;accept=image/png``;
an ``https://`` source without such an ``;accept=`` stays the text source it always was.

INVARIANT (opt-in, no grammar change, round 8): an ``http(s)://`` source is an attachment source
iff its ``;accept=`` is EXACTLY one lower-case type of :data:`ATTACHMENT_TYPES` — no wildcard, no
list, no case folding, no parameter. Any other ``;accept=``, or none, makes it a text source with
today's semantics, untouched.
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
from url4.core.nodes import RelUrl, Source, Url, VarRef

ATTACHMENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
)
"""The attachment types: an ``;accept=`` value that opts a source in, and the response type
it must then carry (F1b round 8: the response's bare type EQUALS the requested one).

WHY a fail-closed subset of the gateway gate (any image for ``image_url``, PDF for ``file``):
nothing outside this set can become an attachment, whatever the origin answers.
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


def is_attachment_accept(accept: str | None) -> bool:
    """Whether ``accept`` is exactly one attachment type, byte for byte (F1b round 8)."""
    return accept in ATTACHMENT_TYPES


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


def non_literal_attachment(node: Source) -> str | None:
    """The target text of a source that asks to be an attachment but is not literal, else None.

    INVARIANT (owner decision C, 2026-10-27 — row-derived attachment URLs deferred): an exact
    attachment ``;accept=`` on a variable (``src=$item;accept=image/png``) or a substituted
    relative path (``/files/$name``) is refused with ``x.source_not_static`` before any fetch,
    never silently read as text. v1 attachment sources have a literal URL and a literal
    ``;accept=``. A literal absolute URL never substitutes, so it is never refused here.
    """
    value = node.value
    target = None
    if isinstance(value, VarRef):
        target = "$" + ".".join((value.name, *map(str, value.path)))
    elif isinstance(value, RelUrl) and "$" in value.value:
        target = value.value
    accept = dict(node.annotations).get("accept")
    return target if target is not None and is_attachment_accept(accept) else None


def classify(identity: AttachmentIdentity, content_type: str | None) -> str:
    """The attachment's bare media type, or ``unsupported_content_type`` (permanent, C8).

    INVARIANT (no sniffing, F1b round 8): the response's one bare, lower-cased media type must
    EQUAL the requested ``;accept=`` type (itself an attachment type). A missing Content-Type,
    one that is not exactly one media type, or any other type is refused alike.
    """
    media_type = _bare_type(content_type)
    if identity.accept in ATTACHMENT_TYPES and media_type == identity.accept:
        return identity.accept
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


def not_static(where: str) -> ResolutionError:
    """``x.source_not_static`` (permanent): an attachment target that is not a literal URL
    known before the first model call (a variable, or a source a model output gates)."""
    return ResolutionError(
        f"attachment source {where} is not static: v1 attachment sources need a literal URL "
        "reachable without a model output, so it cannot be materialized before the first "
        "model call",
        code=ErrorCode.SOURCE_NOT_STATIC,
        permanent=True,
    )


__all__ = [
    "ATTACHMENT_TYPES",
    "AttachmentIdentity",
    "GuardPolicy",
    "classify",
    "guard_policy",
    "identity_of",
    "is_attachment_accept",
    "non_literal_attachment",
    "not_static",
]
