"""CV-2 (characterisation): a cache hit returns before any credential is resolved.

FEATURE: OME-1307 (E14) - capture must not add a credential read to the hit path.
INVARIANT: this test passes before capture exists and must stay green after the capture hooks.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.unit.cache_versions.conftest import traceparent
from tests.unit.test_chat_global_cache_route import (
    _CHAT_PATH,
    _PATCH_TARGET,
    _arrange_account,
    _chat_body,
    _DispatchCounter,
)

_TRACE = "1" * 32


def test_cache_hit_returns_before_credential_resolution(
    capture_client: TestClient, credential_blobs: Any
) -> None:
    from aigateway.core.credential_blob.store import ORMStore

    _arrange_account(capture_client, credential_blobs)
    counter = _DispatchCounter()
    services: list[str] = []
    original = ORMStore.read

    async def _recording(self: Any, service: str, account: str) -> Any:
        services.append(service)
        return await original(self, service, account)

    headers = {"traceparent": traceparent(_TRACE)}
    with patch.object(ORMStore, "read", _recording), patch(_PATCH_TARGET, counter):
        miss = capture_client.post(_CHAT_PATH, json=_chat_body(), headers=headers)
        assert miss.headers["X-AIGW-Cache"] == "miss"
        # Control: unless the miss read an Anthropic credential, the assertion on the hit
        # below would pass vacuously.
        assert [s for s in services if s.startswith("aigateway:anthropic:")], (
            f"the miss read no anthropic credential, so this test proves nothing: {services}"
        )

        services.clear()
        hit = capture_client.post(_CHAT_PATH, json=_chat_body(), headers=headers)

    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert len(counter.calls) == 1, "no dispatch on a hit"
    assert not [s for s in services if s.startswith("aigateway:anthropic:")], (
        f"a hit read an aigateway:anthropic:* credential: {services}"
    )
