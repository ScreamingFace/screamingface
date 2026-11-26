"""The cleanup of one POST /v1/chat/completions request: its input blob and its run.

INVARIANT: the input blob is deleted on every exit after its write, and the run is stopped on
every exit that has no terminal frame. Both run in one shielded task, so a cancelled request
cannot cancel its own cleanup (CC-S26). The write runs as its own task behind a shield, and the
delete waits for that task (RR-S4).

INVARIANT (CC-S35): the cleanup keeps the digest, the scope and the topic, never the record.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from screamingface_engine.artifacts.blob_schema import BlobError, BlobScope, StoredBlob
from screamingface_engine.artifacts.blobs import BlobStore
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.chat.input import CHAT_INPUT_MEDIA_TYPE
from screamingface_engine.rest.chat_body import ChatBody
from screamingface_engine.rest.chat_errors import ChatError

__all__ = ["ChatCleanup"]

_logger = logging.getLogger(__name__)

# WHY a module-level set: the event loop keeps only a weak reference to a task, so a cleanup that
# outlives its cancelled request must be held here until it ends.
_CLEANUPS: set[asyncio.Task[None]] = set()


class ChatCleanup:
    """The input blob of one request and its run: deleted, and stopped when needed.

    The write runs as its own task behind a shield.
    """

    def __init__(
        self,
        store: BlobStore,
        scope: BlobScope,
        digest: str,
        stop: Callable[[str], Awaitable[None]],
        topic: str,
    ) -> None:
        self._store, self._scope, self._sha256 = store, scope, digest
        self._stop, self._topic = stop, topic
        self._write: asyncio.Future[tuple[StoredBlob, bool]] | None = None
        self.scheduling = False
        self.finished = False

    async def write(self, body: ChatBody) -> str:
        """C4: write the CHAT_INPUT record before the schedule; its blob ref."""
        record = body.take_record()
        # WHY: the write is its own task, so a cancel of the request leaves it running, and the
        # cleanup waits for it (RR-S4).
        self._write = asyncio.ensure_future(
            asyncio.to_thread(
                self._store.ingest, self._scope, self._sha256, CHAT_INPUT_MEDIA_TYPE, record
            )
        )
        try:
            blob, _ = await asyncio.shield(self._write)
        except (BlobError, S3StorageError, OSError) as exc:
            _logger.warning(
                "chat input write failed digest=sha256:%s size=%d: %s",
                self._sha256,
                len(record),
                type(exc).__name__,
            )
            raise ChatError(503, "chat_unavailable") from None
        return blob.ref

    async def run(self) -> None:
        """Run the cleanup in its own task and wait for it; a cancel does not stop it."""
        stop = self.scheduling and not self.finished
        if not (self._write is not None or stop):
            return
        task = asyncio.ensure_future(self._clean(stop))
        _CLEANUPS.add(task)
        task.add_done_callback(_CLEANUPS.discard)
        await asyncio.shield(task)

    async def _clean(self, stop: bool) -> None:
        if stop:
            try:
                await self._stop(self._topic)
            # WHY any error: the delete below must still run.
            except Exception as exc:
                _logger.warning("chat run stop failed: %s", type(exc).__name__)
        # INVARIANT (RR-S4): the delete runs after the write has ended, its result or its error.
        if self._write is not None:
            await asyncio.gather(self._write, return_exceptions=True)
        try:
            await asyncio.to_thread(self._store.delete, self._scope, self._sha256)
        # WHY any error: the store sweep is the safety net.
        except Exception as exc:
            _logger.warning(
                "chat input delete failed digest=sha256:%s: %s", self._sha256, type(exc).__name__
            )
