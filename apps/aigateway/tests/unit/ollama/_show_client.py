"""A fake bounded discovery transport that answers Ollama ``POST /api/show`` (OME-1537).

Shared by the Ollama modality tests: records every probe, tracks the peak number of
probes in flight, and can delay or fail each one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

from aigateway.core.parameter_discovery import DiscoveryError, RawResponse


class ShowClient:
    """``DiscoveryHttpClient`` + ``DiscoveryPostClient`` double for ``/api/show``."""

    def __init__(
        self,
        capabilities: Mapping[str, object],
        *,
        delay_s: float = 0.0,
        fail: bool = False,
    ) -> None:
        self._capabilities = dict(capabilities)
        self.delay_s = delay_s
        self.fail = fail
        self.asked: list[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError(f"Ollama modality discovery must not GET {url}")

    async def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, object],
        timeout_s: float,
        max_bytes: int,
    ) -> RawResponse:
        assert url.endswith("/api/show")
        name = str(json_body["model"])
        self.asked.append(name)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            if self.fail:
                raise DiscoveryError("unreachable")
            body = json.dumps({"capabilities": self._capabilities.get(name)})
            return RawResponse(status=200, content_type="application/json", body=body)
        finally:
            self.in_flight -= 1
