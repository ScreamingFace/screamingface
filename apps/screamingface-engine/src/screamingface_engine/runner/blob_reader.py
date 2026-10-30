"""Bind the run blob store's reader around one Runner run (epic OME-1529; OME-1545 x OME-1540).

FEATURE: image and PDF inputs. When the frozen url4 snapshot holds only the ref of a file the App
stored for this run, the model call reads it through the run-scoped ``BlobReader`` port
(``world.attachment_parts``). This module is the Runner's composition of that port: the
``ScopedBlobReader`` over the same backend the App writes, scoped to the run's topic and verified
identity (spec ``docs/spec/2026-10-16-OME-1535-file-input-execution.md`` F3 step 1).

INVARIANT: store corruption (``BlobDigestMismatch``) leaves this adapter as the connector's own
permanent ``x.blob_digest_mismatch`` — one failure, one message naming only the digest.
INVARIANT: an env naming no run (no topic, or one that is not a run id) binds nothing, so a
ref-only attachment stays ``source_not_found`` — the behaviour before this binding existed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext

from screamingface_engine.artifacts.blobs import BlobDigestMismatch, ScopedBlobReader
from screamingface_engine.artifacts.wiring import blob_scope_from_env, blob_store_from_env
from screamingface_engine.world.attachment_parts import bound_blob_reader, digest_mismatch

logger = logging.getLogger(__name__)


class _RunBlobReader:
    """The ``BlobReader`` port over the run's ``ScopedBlobReader``, in the connector's errors."""

    def __init__(self, inner: ScopedBlobReader) -> None:
        self._inner = inner

    async def read(self, digest: str) -> bytes | None:
        try:
            return await self._inner.read(digest)
        except BlobDigestMismatch as exc:
            raise digest_mismatch(digest) from exc


def bound_run_blob_reader(env: Mapping[str, str]) -> AbstractContextManager[None]:
    """This run's blob-reader binding; binds nothing when the env names no run.

    WHY resolved eagerly (here) and bound lazily (on enter): local mode builds the binding in
    ``InProcessJobRunner.schedule`` and enters it inside the run's own task — a misconfigured
    store must refuse at schedule, before a run is admitted, not kill a task that has no stream.
    """
    try:
        scope = blob_scope_from_env(env)
    except ValueError:
        # WHY not raise: the run itself is refused elsewhere when its topic is missing; a reader
        # is only needed for ref-only files, and without a run scope none of them is readable.
        logger.warning("no run blob scope in the run env; ref-only attachments are unreadable")
        return nullcontext()
    # WHY the store is built after the scope: its half-configured-S3 refusal is a real
    # misconfiguration and must still raise, not read as "no run".
    reader = _RunBlobReader(ScopedBlobReader(blob_store_from_env(env), scope))
    return bound_blob_reader(reader)


__all__ = ["bound_run_blob_reader"]
