"""Best-effort bounded delivery on one daemon worker, never the evaluation thread."""

import asyncio
import json
import logging
import queue
import threading
from collections.abc import Callable

import httpx

from screamingface._analytics.ports import Event

_LOG = logging.getLogger(__name__)


async def send_batch(
    client: httpx.AsyncClient, endpoint: str, events: list[Event], allowed: Callable[[], bool]
) -> None:
    envelope = {
        "schema_version": 1,
        "consent_version": "1",
        "consent_granted": True,
        "events": events,
    }
    for attempt in range(2):
        if not allowed():
            return
        try:
            response = await client.post(endpoint, json=envelope)
            if response.status_code not in {429, 503}:
                return
        except (httpx.TransportError, httpx.DecodingError):
            _LOG.debug("Analytics delivery unavailable")
        if attempt == 0:
            await asyncio.sleep(0.05)


class BackgroundSink:
    def __init__(self, endpoint: str, allowed: Callable[[Event], bool]) -> None:
        self.endpoint, self.allowed = endpoint, allowed
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=100)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def emit(self, event: Event) -> None:
        if len(json.dumps(event).encode()) > 4096:
            return
        try:
            self._queue.put_nowait(event.copy())
        except queue.Full:
            return
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run, daemon=True, name="screamingface-analytics"
                )
                self._worker.start()

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        # WHY: the daemon is expendable at interpreter exit; never join or spool.
        while True:
            event = self._queue.get()
            if not self.allowed(event):
                continue
            try:
                asyncio.run(self._send(event))
            except (OSError, RuntimeError, TimeoutError, ValueError):
                _LOG.debug("Analytics batch dropped")

    async def _send(self, event: Event) -> None:
        async with asyncio.timeout(2):
            async with httpx.AsyncClient(
                timeout=2, follow_redirects=False, trust_env=False
            ) as client:
                await send_batch(client, self.endpoint, [event], lambda: self.allowed(event))
