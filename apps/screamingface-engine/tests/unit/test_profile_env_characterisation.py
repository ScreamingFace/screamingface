"""Worker fakes left from the retired Profile queue/env carrier coverage.

The carrier coverage left with OME-1449. The Local listing's label-rule ambiguity, pinned here
for OME-1199, left with OME-1832: the Engine selects the row the gateway flags `effective`, and
no effective row with two or more active ones is refused before any write
(`test_connections_aigateway_effective_writes.py`).
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from url4.streaming.protocol import TerminatedEvent

# --- the worker's fakes: the slice of the queue, the publisher and the child the claim path
# touches, mirroring `test_worker_claim.py` -----------------------------------------------------


class _FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.headers: dict[str, str] | None = None

    async def ack(self) -> None:
        pass

    async def in_progress(self) -> None:
        pass


class _FakePublisher:
    async def last_frame(self, topic: str) -> TerminatedEvent | None:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeProcess:
    """A child that has already exited cleanly."""

    returncode: int | None = 0
    stdout = None
    stderr = None

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class _FakeQueue:
    def __init__(self, batch: list[_FakeMsg]) -> None:
        self._batch: list[_FakeMsg] | None = batch

    async def release_held(self) -> int:
        return 0

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        if self._batch is not None:
            served, self._batch = self._batch, None
            return served
        await asyncio.sleep(timeout_s)
        return []
