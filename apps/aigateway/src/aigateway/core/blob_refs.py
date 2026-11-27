"""A chat request's Case files by blob reference: scope check, key form and swap (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 5). The Engine uploads each Case file (a
picture or PDF of a Benchmark question) to the gateway once per run (`routes/blobs.py`), then
sends each model call with a **reference part**: the inline part with ``blob:sha256/<64 hex>``,
the SHA-256 of the file's bytes, where the ``data:`` URI stood (shape: `content_parts`). This
module turns such a request into what the rest of the gateway already handles:

- the **scope check** (`RunFiles.require`), before the cache lookup: every referenced file must be
  in the store under this caller and this run's token (decision 3);
- the **key form** (`key_form`): the inline request with a `BlobReference` where each ``data:``
  URI would be, which PR 3's key builders hash as the stored file, so the key is today's inline
  key (decision 2);
- the **swap** (`RunFiles.inline`), inside the upstream slot: the inline request itself, built
  from the store just before the provider call, so a waiting request holds only its small JSON.

STORY: as the Engine running a 5-member Fusion on an 18.35 MB PDF, I upload the PDF once and
send six calls of a few KB; the provider still receives exactly today's inline request.
INVARIANT: a file outside this run's scope, or one the store has dropped, is `BlobUnknown`
(503 ``blob_unknown``, not permanent) before any upstream spend. No error carries the token, its
hash or the file's bytes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final, cast

from fastapi import HTTPException

from .content_parts import (
    BlobRefPart,
    UnsupportedContentPart,
    parse_blob_reference,
    reference_digest_of,
)
from .media_store import BlobScope, MediaLookup, StoredMedia
from .request_cache.reference_digest import BlobReference, ReferencedFile

__all__ = [
    "BLOB_UNKNOWN_CODE",
    "BLOB_UNKNOWN_STATUS",
    "BlobUnknown",
    "RunFiles",
    "checked_run_files",
    "key_form",
    "references_in",
]

BLOB_UNKNOWN_CODE: Final = "blob_unknown"
# WHY 503: "not permanent". The Engine treats a 429 or 5xx as retryable and anything else as
# permanent; an unknown file is fixed by uploading it again and repeating the call (PR 8).
BLOB_UNKNOWN_STATUS: Final = 503
# How much of a digest a refusal names: enough to tell files apart, never the file itself.
_DIGEST_PREFIX: Final = 12
# The inner key holding the file, per part type (the reference sits exactly there).
_VALUE_KEY: Final[Mapping[str, str]] = {"image_url": "url", "file": "file_data"}


class BlobUnknown(HTTPException):
    """The gateway holds no such file for this caller's run: upload it again, then repeat.

    One answer for every cause on purpose (another run's token, no token, never uploaded,
    dropped for room, a restart, another gateway pod): telling them apart would tell a caller
    which digests another run holds.
    """

    def __init__(self, sha256: str) -> None:
        """Name the file by a digest prefix only."""
        super().__init__(
            status_code=BLOB_UNKNOWN_STATUS,
            detail={
                "code": "blob_unknown",
                "message": (
                    f"The gateway holds no file sha256/{sha256[:_DIGEST_PREFIX]}… for this run; "
                    "upload it again and repeat the call."
                ),
            },
        )


def references_in(messages: Iterable[Any], *, provider: str) -> list[BlobRefPart]:
    """Every reference part in ``messages``, in order; a malformed one is the typed 422."""
    found: list[BlobRefPart] = []
    for message in messages:
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            continue
        for item in cast("list[object]", content):
            if not isinstance(item, Mapping):
                continue
            reference = parse_blob_reference(cast("Mapping[str, Any]", item), provider=provider)
            if reference is not None:
                found.append(reference)
    return found


def _rewritten(body: Mapping[str, Any], value_for: Callable[[str], Any]) -> dict[str, Any]:
    """``body`` with each reference part as its inline shape, the file's value from ``value_for``.

    The inline shape is the reference part minus ``x_media_type`` and ``x_size``, with
    ``value_for(sha256)`` in the slot the reference held. Containers on the way are copied, so
    ``body`` is never modified; parts that are not references are shared, not copied.
    """
    messages = body.get("messages")
    if not isinstance(messages, list):
        return dict(body)
    rewritten: list[Any] = []
    for message in cast("list[Any]", messages):
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list) or not any(map(reference_digest_of, content)):
            rewritten.append(message)
            continue
        parts: list[Any] = []
        for item in cast("list[Any]", content):
            digest: str | None = reference_digest_of(item)
            if digest is None:
                parts.append(item)
                continue
            part_type: str = item["type"]
            inner: dict[str, Any] = dict(item[part_type])
            inner[_VALUE_KEY[part_type]] = value_for(digest)
            parts.append({"type": part_type, part_type: inner})
        rewritten.append({**message, "content": parts})
    return {**body, "messages": rewritten}


def key_form(body: Mapping[str, Any]) -> dict[str, Any]:
    """The request as PR 3's key builders take it: inline shape, a `BlobReference` per file.

    Example: ``{"type": "image_url", "image_url": {"url": "blob:sha256/ab…"},
    "x_media_type": "image/png", "x_size": 4096}`` becomes ``{"type": "image_url",
    "image_url": {"url": BlobReference("ab…")}}``, which hashes as the inline part with
    ``data:image/png;base64,…`` in that slot. WHY no ``x_`` keys: the inline part has none,
    and any key left on the part would change the digest away from the inline request's.
    """
    return _rewritten(body, BlobReference)


class RunFiles:
    """One request's view of its run's uploaded files: the store, read under one scope.

    Args:
        store: the gateway's `MediaStore` (its read side).
        scope: this caller's run (`BlobScope.of(caller, X-AIGW-Run-Token)`); ``None`` when the
            request carried no token, which finds nothing.

    Thread safety (PR 3's open question c): `lookup` also runs in a worker thread, inside the
    key builders. `MediaStore.get` takes the store's lock; ``_sent`` is written only on the
    event loop, by `inline`, before any later digest thread is started, and only read there.
    """

    def __init__(self, store: MediaLookup, scope: BlobScope | None) -> None:
        """Bind the store to this request's scope."""
        self._store: MediaLookup = store
        self._scope: BlobScope | None = scope
        # The files `inline` put into the provider request, by digest (see `lookup`).
        self._sent: dict[str, ReferencedFile] = {}

    def _stored(self, digest: str) -> StoredMedia | None:
        """The file under this scope and digest, as the store holds it now."""
        return self._store.get(self._scope, digest)

    def require(self, references: Iterable[BlobRefPart], *, provider: str) -> None:
        """The scope check: every referenced file is this run's, and is what the part says.

        Runs before the cache lookup (decision 3), because the key is computed from the files
        (decision 2): a call whose files are not this run's must never reach a cached answer,
        even one an inline call stored for the same bytes.

        Stages, in execution order, per reference:

        1. Look the digest up under this request's scope only. Nothing found (another run's
           token, no token, another caller, never uploaded, dropped) → `BlobUnknown`.
        2. Compare the stored file with what the part declares: ``x_media_type`` with the type
           the upload read from the file's leading bytes, ``x_size`` with its decoded size.
           A difference → 422 ``unsupported_content_part`` (``blob_reference_mismatch``): the
           key and the provider request use the stored type, so the call would be keyed and
           sent as something it did not say.

        Example: run 1 uploaded a 4,104-byte PNG ``ab…``. Run 1's call naming ``ab…`` as
        ``image/png``, 4,104 bytes passes; run 2's call naming it gets ``blob_unknown``; run 1's
        call naming it ``image/jpeg`` gets the 422.
        """
        for reference in references:
            # Stage 1 — this run's file, or nothing.
            media: StoredMedia | None = self._stored(reference.sha256)
            if media is None:
                raise BlobUnknown(reference.sha256)
            # Stage 2 — the part says what the file is.
            if media.media_type != reference.mime or media.size_bytes != reference.size_bytes:
                raise UnsupportedContentPart(
                    provider=provider,
                    part_type="image_url" if reference.kind == "image" else "file",
                    reason="blob_reference_mismatch",
                )

    def lookup(self, digest: str) -> ReferencedFile | None:
        """PR 3's file lookup: the stored file now, else the one this call already sent.

        Before the swap ``_sent`` is empty, so the cache key reads the store live and a dropped
        file is `UnknownBlobReference` there. After the swap, the frozen-copy capture keys the
        file the provider actually received, even if the store dropped it during the call.
        """
        media: StoredMedia | None = self._stored(digest)
        if media is not None:
            return ReferencedFile(media.media_type, media.base64_text)
        return self._sent.get(digest)

    def inline(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """The swap: ``body`` as today's inline request, each file read from the store now.

        In one line: inside the upstream slot, just before the first attempt, each reference
        part becomes exactly the inline part the Engine would have sent, so the provider (and
        every adapter) sees today's request and nothing else.

        Stages, in execution order, per reference part:

        1. Read the file under this scope now, not at the scope check: the call may have waited
           minutes for its slot, and the store may have dropped the file meanwhile (for room,
           or a restart) → `BlobUnknown`, before any upstream spend.
        2. Write the inline part: the reference part minus ``x_media_type`` and ``x_size``,
           with ``data:<stored type>;base64,<stored base64>`` where the reference stood.
        3. Remember the file in ``_sent`` for the frozen-copy capture after the call (`lookup`).

        Example: ``{"type": "image_url", "image_url": {"url": "blob:sha256/ab…", "detail":
        "high"}, "x_media_type": "image/png", "x_size": 4104}`` →
        ``{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0K…",
        "detail": "high"}}``.

        Raises:
            BlobUnknown: a referenced file is no longer held for this run.
        """

        def data_uri(digest: str) -> str:
            """Stages 1 and 3 for one file; stage 2 is `_rewritten`'s."""
            # Stage 1 — read the file now.
            media: StoredMedia | None = self._stored(digest)
            if media is None:
                raise BlobUnknown(digest)
            # Stage 3 — remember what was sent.
            self._sent[digest] = ReferencedFile(media.media_type, media.base64_text)
            return f"data:{media.media_type};base64,{media.base64_text}"

        # Stage 2 — the inline shape around each file.
        return _rewritten(body, data_uri)


def checked_run_files(
    messages: Iterable[Any],
    *,
    store: MediaLookup,
    caller: object,
    token: str | None,
    provider: str,
    streaming: bool,
) -> RunFiles | None:
    """The route's reference stage: ``None`` for an inline request, else this run's checked files.

    A request with no reference part is untouched (``None``). One with references is refused on a
    stream with the typed 422 (``blob_reference_streaming``: a stream commits its 200 before
    dispatch, and has no key or capture to share), else scope-checked (`RunFiles.require`).
    """
    references: list[BlobRefPart] = references_in(messages, provider=provider)
    if not references:
        return None
    if streaming:
        raise UnsupportedContentPart(
            provider=provider,
            part_type="image_url" if references[0].kind == "image" else "file",
            reason="blob_reference_streaming",
        )
    files = RunFiles(store, BlobScope.of(caller, token))
    files.require(references, provider=provider)
    return files
