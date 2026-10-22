"""A non-text ``https://`` body becomes a run attachment (``OME-1543`` U3b, spec F1b).

FEATURE: image and PDF inputs (epic ``OME-1529``). STORY: as an ensemble author I write
``img:src=https://…/photo.png`` and the model calls that read it receive the image as an
attachment, while the payload carries the URL text.

INVARIANT (owner decision Q-B, 2026-10-22): ``https://`` sources stay lazy. Only a body the
text path refused as not-text is re-fetched as bytes; it is sha256-hashed into the run's file
cache and attached at its source position (:class:`~url4.dag.attachments.RunFiles`), once per
digest. A guard refusal on that bytes fetch (``x.source_*``) propagates unchanged.

AIDEV-NOTE: the engine may import only ``io.layer`` (``test_layering``), so the bytes port is
reached duck-typed on ``ctx.io`` (``BoundedIOLayer`` forwards it), as ``BlobRefNode`` does.
Persisting these bytes into the engine's tenant+run store is engine work (Q7, ``run(attachments=…)``
stays the injection point, Q-D); here they live in the run cache only.
"""

from __future__ import annotations

import hashlib

from url4.core.errors import ResolutionError
from url4.dag.attachment import OCTET_STREAM, Attachment
from url4.dag.attachments import CachedBlob, current_run_files
from url4.dag.node import ExecutionContext
from url4.io.layer import FetchRequest


def cached_web_attachment(url: str) -> bool:
    """Whether this run already attached ``url``'s body (so no node fetches it again)."""
    files = current_run_files()
    return files is not None and url in files.fetched


async def attach_web_body(
    ctx: ExecutionContext, request: FetchRequest, refused: ResolutionError
) -> Attachment:
    """Fetch ``request`` as bytes, hash it, and attach it to the bound run.

    Outside a ``run()`` (nothing to attach to) or on an adapter with no bytes port, the text
    path's ``unsupported_content_type`` refusal is raised unchanged.
    """
    files = current_run_files()
    fetch = getattr(ctx.io, "fetch_bytes", None)
    if files is None or fetch is None:
        raise refused
    got = await fetch(request)
    body: bytes = got.body
    attachment = Attachment(
        digest=f"sha256:{hashlib.sha256(body).hexdigest()}",
        media_type=got.media_type or OCTET_STREAM,
        body=body,
    )
    files.attach_fetched(request.target, CachedBlob(body, got.media_type), attachment)
    return attachment


__all__ = ["attach_web_body", "cached_web_attachment"]
