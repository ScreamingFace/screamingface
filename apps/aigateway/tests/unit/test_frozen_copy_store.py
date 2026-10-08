"""Store-level behaviour: capture order, the accessor and the shared helpers (OME-1307)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

from fastapi import HTTPException
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import FrozenCopyEntry
from aigateway.core.frozen_copy.store import (
    FrozenCopyStore,
    frozen_copy_store_for,
    log_capture_failure,
)
from aigateway.core.request_hardening import prepare_ingress_body
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    chat_body,
    chat_response,
    run_async,
    seed_copy,
    stored_entries,
)


def _replay(client: TestClient, copy_id: str, occurrence: int) -> str:
    response = client.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions",
        json=chat_body(),
        headers={"X-AIGW-Replay-Occurrence": str(occurrence)},
    )
    return response.json()["id"]


def test_entries_get_a_per_copy_sequence_in_capture_order(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    owner = account_id_of(client)
    entries: list[Any] = [("chat", {"n": i}, {"r": i}, 200) for i in range(3)]
    first = seed_copy(client, owner, entries, seal=False)
    second = seed_copy(client, owner, entries[:2], seal=False)

    assert [e["seq"] for e in stored_entries(client, first)] == [1, 2, 3]
    assert [e["seq"] for e in stored_entries(client, second)] == [1, 2]


def test_replay_order_follows_seq_not_the_clock(authenticated_client: TestClient) -> None:
    """Two rows can share a timestamp, or the clock can step back: `seq` alone decides."""
    client = authenticated_client
    copy_id = seed_copy(
        client,
        account_id_of(client),
        [("chat", chat_body(), chat_response(m), 200) for m in ("a", "b", "c")],
    )

    async def _scramble_clock() -> None:
        # Reverse the timestamps: capture order a, b, c now looks like c, b, a by created_at.
        for seq, stamp in ((1, "2030-01-03"), (2, "2030-01-02"), (3, "2030-01-01")):
            await FrozenCopyEntry.filter(frozen_copy_id=copy_id, seq=seq).update(
                created_at=f"{stamp}T00:00:00+00:00"
            )

    run_async(client, _scramble_clock)

    assert [_replay(client, copy_id, n) for n in (0, 1, 2)] == ["a", "b", "c"]


def test_the_latest_error_is_the_highest_seq(authenticated_client: TestClient) -> None:
    client = authenticated_client
    body = chat_body()
    copy_id = seed_copy(
        client,
        account_id_of(client),
        [
            ("chat", body, {"detail": "first"}, 500),
            ("chat", body, {"detail": "last"}, 503),
        ],
    )

    async def _scramble_clock() -> None:
        await FrozenCopyEntry.filter(frozen_copy_id=copy_id, seq=2).update(
            created_at="2000-01-01T00:00:00+00:00"
        )

    run_async(client, _scramble_clock)
    response = client.post(f"/v1/frozen-copies/{copy_id}/chat/completions", json=body)

    assert response.status_code == 503
    assert response.json()["detail"] == "last"


def test_one_accessor_gives_the_store_with_the_configured_cap(
    authenticated_client: TestClient,
) -> None:
    app = authenticated_client.app

    first = frozen_copy_store_for(app)
    second = frozen_copy_store_for(app)

    assert isinstance(first, FrozenCopyStore)
    assert first is second
    assert first.max_entry_bytes == app.state.settings.frozen_copy_max_entry_bytes  # type: ignore[attr-defined]


def test_the_shared_log_helper_names_copy_kind_and_digest_prefix_only(caplog) -> None:
    request = {"messages": [{"content": "PROMPT-TEXT"}]}

    with caplog.at_level(logging.WARNING):
        log_capture_failure(
            "chat", RuntimeError("PROMPT-TEXT in message"), copy_id="abc", request=request
        )
        log_capture_failure("tool", RuntimeError("x"))

    lines = [r.getMessage() for r in caplog.records if "frozen copy capture" in r.getMessage()]
    assert len(lines) == 2
    assert "copy=abc" in lines[0] and "kind=chat" in lines[0] and "RuntimeError" in lines[0]
    assert "PROMPT-TEXT" not in caplog.text
    assert "copy=n/a" in lines[1] and "digest=n/a" in lines[1]


def test_prepare_ingress_body_pops_cache_and_strips_dispatch_controls() -> None:
    body = chat_body(cache={"use-cache": False}, api_base="http://example.invalid")

    prepared, controls = prepare_ingress_body(body)

    assert prepared == chat_body()
    assert controls.participate is False


def test_an_inert_capture_never_touches_exception_headers() -> None:
    from aigateway.routes.chat import _Capture

    inert = _Capture(FrozenCopyStore(max_entry_bytes=1), {}, None, None)
    exc = HTTPException(status_code=400, detail="x")
    request = SimpleNamespace(state=SimpleNamespace())

    asyncio.run(inert.record_exception(cast(Any, request), exc))

    assert exc.headers is None
    assert not hasattr(request.state, "aigw_capture_headers")
