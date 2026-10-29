"""Turn the run's url4 ``attachments[]`` into OpenAI content parts for one model call.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1545``; spec
``docs/spec/2026-10-16-OME-1535-file-input-execution.md`` F2, F3).
STORY: as an ensemble author I name a picture or a PDF once in a url4 expression, and every model
call the run makes — members, synthesizers, reducers — sees it next to its prompt.

INVARIANT (F2 layout): the parts go on the LAST user message, in ``attachments[]`` order, before
that message's own content; earlier messages are never touched (D3), and parts a v2 Case envelope
already wrote keep their relative position. A call with no attachments is not touched at all, so a
text-only request stays byte-identical to today.
INVARIANT (F3 canonical encoding): ``data:<lowercased media type>;base64,<payload>`` with standard,
padded RFC 4648 §4 base64, no line breaks and no media-type parameters — so equal files give
byte-identical gateway requests and the gateway cache needs no change in v1.
INVARIANT (F3 integrity): bytes are verified against the digest before any part is built; a
mismatch is ``x.blob_digest_mismatch``, an unreadable digest ``source_not_found``. Neither error
nor any log carries the bytes — the digest names the file.

AIDEV-NOTE: the engine never fetches over the network here. Bytes come from the frozen url4
snapshot (``body``, already verified and run-scoped by url4 at run start) or, when the snapshot
holds only the ref, from the :class:`BlobReader` the engine wiring binds for the run
(:func:`bound_blob_reader`; the Runner binds the run blob store's, ``OME-1540``, in
``runner.blob_reader``; with no reader bound the ref cannot be read).
AIDEV-NOTE: this module imports no url4 engine surface (``test_only_engine_extensions_import_url4``
confines that to the listed adapters): an attachment is read structurally (:class:`AttachmentRef`,
which ``url4.Attachment`` satisfies) and failures are :class:`AttachmentPartError`, which the
connector turns into a url4 ``ResolutionError``.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Literal, Protocol

from screamingface_engine.benchmarks.candidate_input import (
    ContentPart,
    FileData,
    FilePart,
    ImagePart,
    ImageUrl,
)

_SHA256_PREFIX = "sha256:"
SOURCE_NOT_FOUND = "source_not_found"
BLOB_DIGEST_MISMATCH = "x.blob_digest_mismatch"
INTENT_ERROR = "intent_error"
UNSUPPORTED_CONTENT_PART = "unsupported_content_part"


class AttachmentRef(Protocol):
    """One entry of the run's ``attachments[]`` (spec F2 record), as ``url4.Attachment`` has it."""

    @property
    def digest(self) -> str: ...
    @property
    def media_type(self) -> str: ...
    @property
    def body(self) -> bytes: ...
    @property
    def filename(self) -> str | None: ...
    @property
    def detail(self) -> Literal["auto", "low", "high"] | None: ...


class BlobReader(Protocol):
    """The engine's read port onto the run blob store (``OME-1540``).

    INVARIANT (F3 authorization): the wiring binds a reader scoped to ONE tenant + run, taken from
    the run context and never from the request or the ref; a digest outside that scope reads as
    ``None``, indistinguishable from a missing blob. Whatever comes back is verified here.
    """

    async def read(self, digest: str) -> bytes | None:
        """The stored bytes of ``digest`` (``sha256:<hex>``), or ``None`` when not readable."""
        ...


class AttachmentPartError(Exception):
    """A file that cannot become a part: ``code`` is the spec §4 code; always permanent."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


# WHY a ContextVar, not a handler field: the reader is scoped to one tenant + run (F3 step 1), and
# the model handler is world-level and holds no per-run state (prd/01 F2); spawned url4 fragments
# inherit the binding like they inherit the request scope.
_reader: contextvars.ContextVar[BlobReader | None] = contextvars.ContextVar(
    "screamingface_engine_blob_reader", default=None
)


@contextmanager
def bound_blob_reader(reader: BlobReader) -> Iterator[None]:
    """Bind the run's blob reader for the enclosed model calls, restoring on exit."""
    token = _reader.set(reader)
    try:
        yield
    finally:
        _reader.reset(token)


def canonical_data_uri(media_type: str, body: bytes) -> str:
    """The F3 canonical ``data:`` URI of ``body``.

    WHY strip parameters: ``image/png; charset=x`` and ``IMAGE/PNG`` are the same file to a model
    but different request bytes to the gateway cache; F3 allows exactly one spelling.
    """
    bare = media_type.split(";", 1)[0].strip().lower()
    return f"data:{bare};base64,{base64.b64encode(body).decode('ascii')}"


async def attachment_parts(attachments: Sequence[AttachmentRef]) -> list[ContentPart]:
    """One content part per attachment, in ``attachments[]`` order, from verified bytes."""
    return [_part(attachment, await _verified_body(attachment)) for attachment in attachments]


def place_on_last_user_message(
    messages: list[dict[str, Any]], parts: Sequence[ContentPart]
) -> list[dict[str, Any]]:
    """``messages`` with ``parts`` leading the last user message's content (F2, D3).

    A text content becomes ``[parts…, {"type": "text", "text": <text>}]``; a v2 part list becomes
    ``[parts…, <its parts as written>]``. ``messages`` itself is not mutated.
    """
    if not parts:
        return messages
    placed = list(messages)
    for index in range(len(placed) - 1, -1, -1):
        if placed[index].get("role") == "user":
            content = placed[index]["content"]
            own = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
            placed[index] = {**placed[index], "content": [*parts, *own]}
            return placed
    # WHY: every connector chat ends with a user message (a plain prompt, or a Case envelope the
    # reader admitted); reaching here is a programming error, not a request to send the files
    # somewhere else.
    raise ValueError("a chat with attachments has no user message to carry them")


def _part(attachment: AttachmentRef, body: bytes) -> ContentPart:
    url = canonical_data_uri(attachment.media_type, body)
    if url.startswith("data:image/"):
        image: ImageUrl = {"url": url}
        if attachment.detail is not None:
            image["detail"] = attachment.detail
        return ImagePart(type="image_url", image_url=image)
    # WHY every non-image type becomes a ``file`` part (F2 "otherwise"): which file types a model
    # may take is the gateway's per-type policy (PDF only today), refused there by name.
    file: FileData = {"file_data": url}
    if attachment.filename is not None:
        file["filename"] = attachment.filename
    return FilePart(type="file", file=file)


async def _verified_body(attachment: AttachmentRef) -> bytes:
    """The attachment's bytes, verified against its digest (F3 step 3)."""
    if _hashes_to(attachment.body, attachment.digest):
        return attachment.body
    if attachment.body:
        raise digest_mismatch(attachment.digest)
    # WHY: an empty body that does not hash to the digest means the snapshot holds only the ref.
    reader = _reader.get()
    stored = None if reader is None else await reader.read(attachment.digest)
    if stored is None:
        raise AttachmentPartError(
            f"attachment {attachment.digest} is not readable in this run", code=SOURCE_NOT_FOUND
        )
    if not _hashes_to(stored, attachment.digest):
        raise digest_mismatch(attachment.digest)
    return stored


def _hashes_to(body: bytes, digest: str) -> bool:
    return (
        digest.startswith(_SHA256_PREFIX)
        and hashlib.sha256(body).hexdigest() == digest[len(_SHA256_PREFIX) :]
    )


def digest_mismatch(digest: str) -> AttachmentPartError:
    """The permanent ``x.blob_digest_mismatch`` for ``digest``; the message names the digest only.

    Public so a reader adapter whose store detects corruption itself (the run blob store,
    ``OME-1540``) raises the very failure this module raises, not a second spelling of it.
    """
    return AttachmentPartError(
        f"attachment bytes do not hash to {digest}", code=BLOB_DIGEST_MISMATCH
    )


class GatewayContentPartRefusal(Exception):
    """The gateway's ``unsupported_content_part`` refusal, kept as the cause of an ``intent_error``.

    ``info`` is the gateway's own detail (``code``, ``provider``, ``part_type``, ``reason``,
    ``message``), copied so the cause cannot change after the fact.
    """

    def __init__(self, info: dict[str, Any]) -> None:
        self.info = dict(info)
        super().__init__(str(self.info.get("message", UNSUPPORTED_CONTENT_PART)))


def intent_error_for(detail: dict[str, Any]) -> GatewayContentPartRefusal | None:
    """The refusal to raise ``intent_error`` from, or ``None`` for any other gateway code.

    WHY the one exception to verbatim wrapping (spec #1450 §4): in url4 terms a model that cannot
    take a part is an admission condition (C9), so the gateway backstop's code is translated to
    ``intent_error``; the caller keeps the response's permanence. Every other code stays as is.
    """
    if detail.get("code") != UNSUPPORTED_CONTENT_PART:
        return None
    return GatewayContentPartRefusal(detail)


__all__ = [
    "BLOB_DIGEST_MISMATCH",
    "INTENT_ERROR",
    "SOURCE_NOT_FOUND",
    "UNSUPPORTED_CONTENT_PART",
    "AttachmentPartError",
    "AttachmentRef",
    "BlobReader",
    "GatewayContentPartRefusal",
    "attachment_parts",
    "bound_blob_reader",
    "canonical_data_uri",
    "digest_mismatch",
    "intent_error_for",
    "place_on_last_user_message",
]
