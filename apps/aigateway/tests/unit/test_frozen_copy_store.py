"""Store-level behaviour: capture order, the accessor and the shared helpers (OME-1307)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.auth.models import Account
from aigateway.core.frozen_copy.models import FrozenCopyEntry
from aigateway.core.frozen_copy.store import (
    FrozenCopyStore,
    frozen_copy_store_for,
    log_capture_failure,
    request_digest,
)
from aigateway.core.request_hardening import prepare_ingress_body
from tests.unit.test_frozen_copy_support import (
    CASE_A,
    CASE_KEY_HEADER,
    OCCURRENCE_HEADER,
    account_id_of,
    call_key,
    chat_body,
    chat_response,
    run_async,
    seed_copy,
    seed_keyed_copy,
    store,
    stored_entries,
)


def _replay(client: TestClient, copy_id: str, occurrence: int, case_key: str = "") -> str:
    response = client.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions",
        json=chat_body(),
        headers=call_key(case_key, occurrence),
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

    # Three successes at one key: the latest one by `seq` ("c"), whatever the clock says.
    assert _replay(client, copy_id, 0) == "c"


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
    response = client.post(
        f"/v1/frozen-copies/{copy_id}/chat/completions", json=body, headers=call_key()
    )

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


async def _anonymous_account_stored() -> bool:
    return await Account.filter(id=ANONYMOUS_ACCOUNT_ID).exists()


def test_the_anonymous_account_opens_a_copy_without_a_foreign_key_failure(
    authenticated_client: TestClient,
) -> None:
    """With auth disabled the caller is an unsaved anonymous account; opening a copy stores it."""
    store = frozen_copy_store_for(authenticated_client.app)
    assert not run_async(authenticated_client, _anonymous_account_stored)

    copy = run_async(authenticated_client, lambda: store.open(ANONYMOUS_ACCOUNT_ID))

    assert copy.account_id == ANONYMOUS_ACCOUNT_ID
    assert run_async(authenticated_client, _anonymous_account_stored)


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


def test_an_attempt_number_digests_apart_from_attempt_one() -> None:
    request = chat_body()

    assert request_digest("chat", request) == request_digest("chat", request, None)
    assert request_digest("chat", request, 2) != request_digest("chat", request)
    assert request_digest("chat", request, 2) != request_digest("chat", request, 3)


def test_a_reused_key_keeps_the_latest_success_and_the_error_falls_behind(
    authenticated_client: TestClient,
) -> None:
    """An error entry at a key and the later success that reused the key can coexist. The lookup
    serves the latest success at the key, else the latest error (design §4.4)."""
    client = authenticated_client
    request = chat_body()
    copy_id = seed_keyed_copy(
        client,
        account_id_of(client),
        [
            (CASE_A, 0, request, {"detail": "gateway down"}, 503),
            (CASE_A, 0, request, chat_response("slot-0-retry"), 200),
            (CASE_A, 1, request, chat_response("slot-1"), 200),
        ],
    )

    assert _replay(client, copy_id, 0, CASE_A) == "slot-0-retry"
    assert _replay(client, copy_id, 1, CASE_A) == "slot-1"


def test_two_entries_of_one_copy_never_share_a_seq(authenticated_client: TestClient) -> None:
    """Q27 follow-up: the (copy, seq) uniqueness makes a row-lock regression fail loudly."""
    from aigateway.core.frozen_copy.models import FrozenCopyEntry

    client = authenticated_client
    owner = account_id_of(client)

    async def _create_duplicate() -> None:
        frozen = store()
        copy = await frozen.open(owner)
        await frozen.capture(copy, "chat", {"n": 1}, {"r": 1}, 200)
        await FrozenCopyEntry.create(
            frozen_copy_id=copy.id,
            kind="chat",
            request_digest="dup",
            request_json={"n": 2},
            response_json={"r": 2},
            status_code=200,
            seq=1,
        )

    with pytest.raises(Exception, match="(?i)unique constraint"):
        run_async(client, _create_duplicate)


def test_a_bad_or_missing_call_key_is_malformed_not_absent() -> None:
    """Design §4.2: a case key is "" or 32 lowercase hex; an occurrence is 1 to 9 ASCII digits.
    Anything else is malformed. Capture reads it as refused, never as absent (Q27)."""
    from aigateway.core.frozen_copy.headers import MalformedCallKey, parse_call_key

    assert parse_call_key({CASE_KEY_HEADER: CASE_A, OCCURRENCE_HEADER: "0"}) == (CASE_A, 0)
    assert parse_call_key({OCCURRENCE_HEADER: "12"}) == ("", 12)
    assert parse_call_key({CASE_KEY_HEADER: "", OCCURRENCE_HEADER: "999999999"}) == ("", 999999999)

    for headers in (
        {},
        {CASE_KEY_HEADER: CASE_A},
        {OCCURRENCE_HEADER: ""},
        {OCCURRENCE_HEADER: "+3"},
        {OCCURRENCE_HEADER: " 3"},
        {OCCURRENCE_HEADER: "1_0"},
        {OCCURRENCE_HEADER: "-1"},
        {OCCURRENCE_HEADER: "\u0663"},
        {OCCURRENCE_HEADER: "1234567890"},
        {CASE_KEY_HEADER: "A" * 32, OCCURRENCE_HEADER: "0"},
        {CASE_KEY_HEADER: "a" * 31, OCCURRENCE_HEADER: "0"},
    ):
        with pytest.raises(MalformedCallKey):
            parse_call_key(headers)
