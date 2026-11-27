"""Send a Case's files to the gateway once per run, and by blob reference on every call.

FEATURE (OME-1970, PR 7): a **Case** file (a picture or PDF) rode every model call inline as
base64, so a 5-member Fusion on a 13.76 MB PDF sent six requests of 18.35 MB. Now, with the world's
``blob_refs`` flag on, the Engine uploads each file once per run to the gateway
(``PUT /v1/blobs/sha256/{digest}``, aigateway `routes/blobs.py`) and each call carries a **blob
reference**, ``blob:sha256/<64 hex>``, the SHA-256 of the file's bytes, which the gateway swaps
back for the stored file inside the call's upstream slot (aigateway `core/blob_refs.py`).

Stages of one call, in execution order (`reference_parts`):

1. Find each inline file part: an ``image_url`` or ``file`` part whose value is exactly
   ``data:<type>;base64,<text>``. Anything else (text, a ``data:`` URI with parameters) is left
   as it is.
2. Decode it and take its SHA-256 and size, off the event loop.
3. Upload it unless this run already did (`RunCaseFiles.stored_type`): one upload per file per
   run, shared by every call that needs it at once, a Fusion's members included.
4. Write the reference part: the inline part with the reference where the ``data:`` URI stood,
   plus ``x_media_type`` and ``x_size`` (the gateway checks both against what it stored).

Worked example: a 13,760,000-byte PDF ``ab12…``, 5 members and a synthesizer. Call 1 uploads it
once under this run's token; calls 1-6 each send ``{"type": "file", "file": {"file_data":
"blob:sha256/ab12…"}, "x_media_type": "application/pdf", "x_size": 13760000}``, a few hundred
bytes where 18,346,668 of base64 stood.

INVARIANT (decision 3): a file is usable only under the caller AND this run's **run token**, a
random value minted here once per run and sent on the upload and on every call. A SHA-256 alone
never reaches another run's file. The token never appears in a repr or a log line.
INVARIANT: the path is chosen once per run. If the first upload finds no upload route (an older
gateway), the whole run sends inline, exactly as before this feature.
INVARIANT: a request in inline form is never changed here; the swap returns new containers, so
the frozen copy's request digest (`capture_outcomes.request_digest`) keeps hashing the inline form.

AIDEV-NOTE (PR 8 seam): the gateway answers 503 ``blob_unknown`` when it no longer holds a file
(dropped for room, or a restart). The fix is to drop that digest from `RunCaseFiles._uploads` and
call again, so the next `stored_type` uploads it anew; that retry lands in OME-1970 PR 8.
AIDEV-NOTE: the Engine never streams a chat call (``stream`` is a Runner-owned field nothing
sets), so no reference reaches the gateway's streaming 422 (``blob_reference_streaming``); the
transport still leaves a streaming body inline.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

RUN_TOKEN_HEADER = "X-AIGW-Run-Token"
"""The header carrying the run token, the gateway's own name for it (`routes/blobs.py`)."""

BLOB_UPLOAD_PATH = "/v1/blobs/sha256/{digest}"
"""The gateway's upload route; ``digest`` is 64 lowercase hex characters."""

_REFERENCE_PREFIX = "blob:sha256/"
# Where each file part keeps its data: URI (the gateway's `_REFERENCE_VALUE_KEY`).
_VALUE_KEY: Mapping[str, str] = {"image_url": "url", "file": "file_data"}
# WHY no parameters admitted: the gateway writes the stored file back as exactly
# `data:<type>;base64,<text>`, so only a part already spelled that way comes back unchanged.
_PLAIN_DATA_URI = re.compile(r"data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,", re.ASCII)
# WHY 32 bytes: `token_urlsafe(32)` is 43 characters, 256 bits; the gateway admits 32 to 256
# URL-safe characters (`routes/blobs.py` `_RUN_TOKEN`).
_TOKEN_BYTES = 32


class CaseFileUploader(Protocol):
    """What can put one file on the gateway for this run (the transport implements it)."""

    async def upload(self, digest: str, data: bytes) -> str | None:
        """Upload ``data`` under ``digest``; the type the gateway read, or ``None`` with no route.

        Raises:
            ResolutionError: the gateway refused the file or could not be reached.
        """
        ...


def _mint_token() -> str:
    """A fresh random run token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


@dataclass(eq=False)
class RunCaseFiles:
    """One run's file uploads: its token, the files already on the gateway, and the chosen path.

    One holder per run, bound by `run_case_files`; url4's member tasks copy the context, so every
    call of the run (a Fusion's members included) shares this object.
    """

    token: str = field(default_factory=_mint_token, repr=False)
    inline: bool = False
    # digest → the upload in flight or done; its result is the type the gateway read.
    _uploads: dict[str, asyncio.Future[str | None]] = field(default_factory=dict, repr=False)

    async def stored_type(self, digest: str, data: bytes, uploader: CaseFileUploader) -> str | None:
        """The type the gateway stored ``digest`` as, uploading it first if this run has not.

        In one line: the first caller starts the upload, every concurrent or later caller awaits
        that same upload, and a failed upload is forgotten so the next call tries again.
        """
        upload: asyncio.Future[str | None] | None = self._uploads.get(digest)
        if upload is None:
            # INVARIANT: registered before this coroutine's first await, so a sibling call
            # scheduled in the same run finds it and never starts a second upload.
            upload = asyncio.ensure_future(uploader.upload(digest, data))
            self._uploads[digest] = upload
            upload.add_done_callback(lambda done: self._forget_failure(digest, done))
        # WHY shield: one cancelled member must not cancel the upload its siblings await.
        return await asyncio.shield(upload)

    def _forget_failure(self, digest: str, done: asyncio.Future[str | None]) -> None:
        """Drop a failed or cancelled upload so the next call uploads the file again."""
        if done.cancelled() or done.exception() is not None:
            self._uploads.pop(digest, None)


_RUN_FILES: ContextVar[RunCaseFiles | None] = ContextVar("case_file_refs_run", default=None)


@contextmanager
def run_case_files() -> Iterator[RunCaseFiles]:
    """Bind a fresh holder, and so a fresh run token, for the length of one run."""
    holder = RunCaseFiles()
    token = _RUN_FILES.set(holder)
    try:
        yield holder
    finally:
        _RUN_FILES.reset(token)


def current_run_files() -> RunCaseFiles | None:
    """This run's holder, or ``None`` outside a run (the sync surface, a bare test)."""
    return _RUN_FILES.get()


# WHY a context value and not a parameter: the flag is the world's (`AigatewayConfig.blob_refs`)
# and the swap is the transport's post, five calls below; the connector marks its own call.
_BY_REFERENCE: ContextVar[bool] = ContextVar("case_file_refs_by_reference", default=False)


@contextmanager
def sent_by_reference(enabled: bool) -> Iterator[None]:
    """Mark the model call in progress as one whose world sends Case files by reference."""
    token = _BY_REFERENCE.set(enabled)
    try:
        yield
    finally:
        _BY_REFERENCE.reset(token)


def reference_run() -> RunCaseFiles | None:
    """The run's holder when this call sends its files by reference, else ``None``.

    ``None`` when the world's flag is off, outside a run, or once the run has turned inline.
    """
    run: RunCaseFiles | None = _RUN_FILES.get()
    if not _BY_REFERENCE.get() or run is None or run.inline:
        return None
    return run


@dataclass(frozen=True, slots=True)
class _InlineFile:
    """One inline file part, measured: what its reference part needs."""

    part_type: str
    mime: str
    sha256: str
    data: bytes


def _inline_file(part: object) -> tuple[str, str, str, int] | None:
    """``(part type, MIME, data: URI, where its base64 starts)`` of a plain inline file part.

    ``None`` for any other part. WHY an offset, not the base64 text: slicing would copy a
    15 MB string on every look; only `_measured` copies it, once, in a worker thread.
    """
    part_type: object = part.get("type") if isinstance(part, Mapping) else None
    if (
        not isinstance(part, Mapping)
        or not isinstance(part_type, str)
        or part_type not in _VALUE_KEY
    ):
        return None
    inner: object = part.get(part_type)
    value: object = inner.get(_VALUE_KEY[part_type]) if isinstance(inner, Mapping) else None
    match = _PLAIN_DATA_URI.match(value) if isinstance(value, str) else None
    if match is None or not isinstance(value, str):
        return None
    return part_type, match["mime"], value, match.end()


def _measured(part_type: str, mime: str, uri: str, start: int) -> _InlineFile:
    """Decode one file and take its SHA-256 (stage 2; run in a worker thread)."""
    data: bytes = base64.b64decode(uri[start:], validate=True)
    return _InlineFile(part_type, mime, hashlib.sha256(data).hexdigest(), data)


def _reference_part(part: Mapping[str, Any], file: _InlineFile) -> dict[str, Any]:
    """The inline ``part`` with the reference where its ``data:`` URI stood (stage 4)."""
    inner: dict[str, Any] = dict(part[file.part_type])
    inner[_VALUE_KEY[file.part_type]] = f"{_REFERENCE_PREFIX}{file.sha256}"
    return {
        "type": file.part_type,
        file.part_type: inner,
        "x_media_type": file.mime,
        "x_size": len(file.data),
    }


async def reference_parts(
    messages: Sequence[Mapping[str, Any]], uploader: CaseFileUploader, scope: RunCaseFiles
) -> list[dict[str, Any]]:
    """``messages`` with each inline file part as a blob reference, each file uploaded once.

    Stages 1-4 of the module docstring. A message with no file part is passed on as it is. If an
    upload finds no route, ``scope`` turns inline for the rest of the run and ``messages`` come
    back unchanged. A part whose file the gateway read as another type stays inline.

    Args:
        messages: the chat messages of one call, inline form; never modified.
        uploader: puts a file on the gateway (`gateway_transport`'s upload route client).
        scope: this run's holder (`current_run_files`).

    Raises:
        ResolutionError: an upload the gateway refused or could not take (from ``uploader``).
    """
    sent: list[dict[str, Any]] = []
    for message in messages:
        content: object = message.get("content")
        # Stage 1 — only a part list can hold a file.
        if not isinstance(content, list) or not any(_inline_file(part) for part in content):
            sent.append(dict(message))
            continue
        parts: list[Any] = []
        for part in content:
            found: tuple[str, str, str, int] | None = _inline_file(part)
            if found is None:
                parts.append(part)
                continue
            # Stage 2 — measure, off the event loop (a 15 MB file takes tens of milliseconds).
            file: _InlineFile = await asyncio.to_thread(_measured, *found)
            # Stage 3 — once per run.
            stored: str | None = await scope.stored_type(file.sha256, file.data, uploader)
            if stored is None:
                scope.inline = True
                return [dict(message) for message in messages]
            # Stage 4 — the reference, unless the gateway would send the file back changed.
            parts.append(part if stored != file.mime else _reference_part(part, file))
        sent.append({**message, "content": parts})
    return sent


__all__ = [
    "BLOB_UPLOAD_PATH",
    "RUN_TOKEN_HEADER",
    "CaseFileUploader",
    "RunCaseFiles",
    "current_run_files",
    "reference_parts",
    "reference_run",
    "run_case_files",
    "sent_by_reference",
]
