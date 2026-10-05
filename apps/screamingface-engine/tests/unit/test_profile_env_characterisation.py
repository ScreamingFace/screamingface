"""Local listing ambiguity characterization and worker fakes shared by queue tests.

The retired Profile queue/env carrier coverage left with OME-1449. The listing's 409 ambiguity
rule is an independent retained consumer obligation from OME-1199 and remains pinned here.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller, ConnectionConflict
from url4.streaming.protocol import TerminatedEvent

pytestmark = pytest.mark.asyncio

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


# The Local listing refuses when more than one managed row exists, whatever its status.


def _adapter(rows: list[dict[str, object]]) -> AigatewayConnections:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "object": "provider",
                            "id": "openrouter",
                            "display_name": "OpenRouter",
                            "auth_methods": ["api_key"],
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"connections": rows})

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handler)
    )
    return AigatewayConnections(client)


def _managed_row(connection_id: str, status: str) -> dict[str, object]:
    return {
        "id": connection_id,
        "account_id": "00000000-0000-0000-0000-000000000099",
        "provider": "openrouter",
        "label": "screamingface",
        "status": status,
        "auth_type": "api_key",
        "account": None,
        "credential_locator": {"service": "must-not-leak", "account": "default"},
        "created_at": "2026-07-31T00:00:00Z",
        "last_used_at": None,
        "last_refreshed_at": None,
        "error_message": None,
        "is_duplicate": False,
    }


_ROW_A = "00000000-0000-0000-0000-000000000001"
_ROW_B = "00000000-0000-0000-0000-000000000002"


@pytest.mark.parametrize("other_status", ["pending", "expired", "error", "revoked"])
async def test_one_active_and_one_other_managed_row_of_any_status_is_a_conflict(
    other_status: str,
) -> None:
    """# INVARIANT (legacy, pinned): `_select` (`connections/aigateway.py:251-257`) counts every
    managed-label row for the provider regardless of `status`; two of them refuse with
    `ConnectionConflict` (409 at the REST edge). The gateway's default listing already hides
    revoked rows (`OAuthConnectionStore.list` excludes them), so in practice the rule reads
    "more than one NON-REVOKED managed row of any status" — but the adapter itself is
    status-blind, which is what a gateway-side reproduction (A3) must know.
    """
    adapter = _adapter([_managed_row(_ROW_A, "active"), _managed_row(_ROW_B, other_status)])

    with pytest.raises(ConnectionConflict):
        await adapter.list(Caller())


async def test_two_non_active_managed_rows_are_a_conflict_too() -> None:
    adapter = _adapter([_managed_row(_ROW_A, "pending"), _managed_row(_ROW_B, "error")])

    with pytest.raises(ConnectionConflict):
        await adapter.list(Caller())


async def test_a_single_non_active_managed_row_is_not_a_conflict() -> None:
    """Control: one managed row, whatever its status, is selected rather than refused."""
    adapter = _adapter([_managed_row(_ROW_A, "pending")])

    (connection,) = await adapter.list(Caller())

    assert connection.status == "pending"
