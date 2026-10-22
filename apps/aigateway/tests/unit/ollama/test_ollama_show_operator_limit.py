"""OME-1537 review (HupBaHa 2026-10-21T15:00Z, Medium) — ``/api/show`` honours the
operator's discovery byte limit.

``AIGW_DISCOVERY_MAX_BYTES`` populates ``DiscoveryLimits.max_bytes``. Each async
``/api/show`` probe must be capped at ``min(SHOW_MAX_BYTES, limits.max_bytes)``: a
stricter operator limit wins, a looser one never raises the show cap above 1 MB.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.plugins.ollama_provider.discovery import (
    DEFAULT_OLLAMA_HOST,
    SHOW_MAX_BYTES,
    clear_ollama_discovery_cache,
    discover_ollama_show_modalities,
)

from ._show_client import ShowClient


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_ollama_discovery_cache()
    yield
    clear_ollama_discovery_cache()


class _RecordingShowClient(ShowClient):
    """Records the ``max_bytes`` each ``/api/show`` probe was given."""

    def __init__(self, capabilities: Mapping[str, object]) -> None:
        super().__init__(capabilities)
        self.max_bytes_seen: list[int] = []

    async def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, object],
        timeout_s: float,
        max_bytes: int,
    ) -> RawResponse:
        self.max_bytes_seen.append(max_bytes)
        return await super().post(
            url, json_body=json_body, timeout_s=timeout_s, max_bytes=max_bytes
        )


_CAPS = {"a:1b": ["completion", "vision"], "b:1b": ["completion"]}


@pytest.mark.asyncio
async def test_a_stricter_operator_byte_limit_caps_every_show_probe() -> None:
    client = _RecordingShowClient(_CAPS)
    await discover_ollama_show_modalities(
        DEFAULT_OLLAMA_HOST, list(_CAPS), client=client, limits=DiscoveryLimits(max_bytes=17)
    )
    assert client.max_bytes_seen == [17, 17]


@pytest.mark.asyncio
async def test_a_looser_operator_byte_limit_never_raises_the_show_cap() -> None:
    client = _RecordingShowClient(_CAPS)
    await discover_ollama_show_modalities(
        DEFAULT_OLLAMA_HOST,
        list(_CAPS),
        client=client,
        limits=DiscoveryLimits(max_bytes=SHOW_MAX_BYTES * 10),
    )
    assert client.max_bytes_seen == [SHOW_MAX_BYTES, SHOW_MAX_BYTES]
