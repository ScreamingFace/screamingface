"""Replay endpoints answer a sealed frozen copy and nothing else (OME-1307, design §4.4)."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.unit.test_frozen_copy_support import (
    CASE_A,
    CASE_B,
    CASE_KEY_HEADER,
    OCCURRENCE_HEADER,
    PATCH_TARGET,
    DispatchCounter,
    account_id_of,
    call_key,
    chat_body,
    chat_response,
    seed_copy,
    seed_keyed_copy,
)

# Occurrence values a caller may send that are not 1 to 9 ASCII digits (design §4.2).
_BAD_OCCURRENCES = ["+3", " 3", "1_0", "-1", "1.5", "", "abc", "1234567890", "٣"]


def _replay_path(copy_id: str) -> str:
    return f"/v1/frozen-copies/{copy_id}/chat/completions"


class _Forbidden:
    """Any attribute access fails: proves the replay never touched the object."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"replay touched {name}")


def test_replay_never_resolves_credentials_or_calls_a_provider(
    authenticated_client: TestClient, monkeypatch
) -> None:
    """The point of replay: it works with no credential, no provider, no model and no cache.

    The model names a provider that is not registered (a retired or removed plugin), and the
    account has no connection at all — so a replay that tried any of them could not succeed.
    """
    from aigateway.core.provider_access.connection_backed import ConnectionBackedProviderAccess
    from aigateway.core.provider_access.profile_backed import ProfileBackedProviderAccess

    forbidden: list[str] = []

    def _spy(label: str):
        async def _record(*_args: Any, **_kwargs: Any) -> None:
            forbidden.append(label)
            raise AssertionError(f"replay reached {label}")

        return _record

    for cls in (ProfileBackedProviderAccess, ConnectionBackedProviderAccess):
        for method in ("resolve", "authorize"):
            monkeypatch.setattr(cls, method, _spy(f"{cls.__name__}.{method}"))
    monkeypatch.setattr(
        "aigateway.routes.chat_dispatch._dispatch_with_backpressure", _spy("dispatch")
    )
    dispatch = DispatchCounter()
    monkeypatch.setattr(PATCH_TARGET, dispatch)
    monkeypatch.setattr(
        cast(Any, authenticated_client.app).state, "request_cache_store", _Forbidden()
    )

    body = chat_body(model="ghost/retired-model")
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", body, chat_response("captured"), 200)],
    )

    response = authenticated_client.post(_replay_path(copy_id), json=body, headers=call_key())

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "captured"
    assert response.headers["X-AIGW-Replay"] == "hit"
    assert forbidden == []
    assert dispatch.calls == []


def _lookup_cases() -> list[Any]:
    ok = lambda case, occurrence, marker: (  # noqa: E731
        case,
        occurrence,
        chat_body(),
        chat_response(marker),
        200,
    )
    err = lambda case, occurrence, status, text: (  # noqa: E731
        case,
        occurrence,
        chat_body(),
        {"detail": {"code": "provider_error", "message": text}},
        status,
    )
    miss = ("miss", None)
    return [
        pytest.param(
            [ok(CASE_A, 0, "a"), ok(CASE_A, 0, "b")],
            CASE_A,
            0,
            ("ok", "b"),
            id="latest-success-at-the-key",
        ),
        pytest.param(
            [err(CASE_A, 0, 503, "e1"), ok(CASE_A, 1, "a")],
            CASE_A,
            0,
            ("error", (503, "e1")),
            id="error-at-zero-and-success-at-one-replays-the-error",
        ),
        pytest.param(
            [err(CASE_A, 0, 503, "e1"), ok(CASE_A, 1, "a")],
            CASE_A,
            1,
            ("ok", "a"),
            id="success-at-one",
        ),
        pytest.param(
            [err(CASE_A, 0, 429, "e1"), ok(CASE_A, 0, "a"), err(CASE_A, 0, 500, "e2")],
            CASE_A,
            0,
            ("ok", "a"),
            id="success-wins-over-later-errors",
        ),
        pytest.param(
            [err(CASE_A, 0, 503, "e1"), err(CASE_A, 0, 500, "e2")],
            CASE_A,
            0,
            ("error", (500, "e2")),
            id="latest-error",
        ),
        pytest.param([ok(CASE_A, 0, "a")], CASE_A, 1, miss, id="occurrence-never-captured"),
        pytest.param([ok(CASE_A, 0, "a")], CASE_B, 0, miss, id="case-never-captured"),
    ]


@pytest.mark.parametrize(("entries", "case_key", "occurrence", "expected"), _lookup_cases())
def test_replay_returns_the_latest_success_at_the_key_else_the_latest_error_else_miss(
    authenticated_client: TestClient,
    entries: list[Any],
    case_key: str,
    occurrence: int,
    expected: tuple,
) -> None:
    copy_id = seed_keyed_copy(authenticated_client, account_id_of(authenticated_client), entries)

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key(case_key, occurrence)
    )

    kind, value = expected
    if kind == "ok":
        assert response.status_code == 200, response.text
        assert response.json()["id"] == value
        assert response.headers["X-AIGW-Replay"] == "hit"
    elif kind == "error":
        status, message = value
        assert response.status_code == status
        assert response.json()["detail"] == {"code": "provider_error", "message": message}
        assert response.headers["X-AIGW-Replay"] == "error"
    else:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "frozen_copy_miss"
        assert "X-AIGW-Replay" not in response.headers


def test_same_request_in_two_cases_replays_each_case_its_own_answer(
    authenticated_client: TestClient,
) -> None:
    """Q27: identical requests in two cases never swap answers."""
    copy_id = seed_keyed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [
            (CASE_A, 0, chat_body(), chat_response("case-a"), 200),
            (CASE_B, 0, chat_body(), chat_response("case-b"), 200),
        ],
    )

    first = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key(CASE_A)
    )
    second = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key(CASE_B)
    )

    assert first.json()["id"] == "case-a"
    assert second.json()["id"] == "case-b"


def test_completion_order_does_not_change_replay(authenticated_client: TestClient) -> None:
    """Q27: occurrence 1 is stored before occurrence 0; each call still gets its own answer."""
    copy_id = seed_keyed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [
            (CASE_A, 1, chat_body(), chat_response("second"), 200),
            (CASE_A, 0, chat_body(), chat_response("first"), 200),
        ],
    )

    def at(occurrence: int) -> str:
        response = authenticated_client.post(
            _replay_path(copy_id), json=chat_body(), headers=call_key(CASE_A, occurrence)
        )
        return response.json()["id"]

    assert [at(0), at(1)] == ["first", "second"]


def test_no_fallback_to_another_occurrence_or_case_key(authenticated_client: TestClient) -> None:
    """Q27: a call with no entry at its own key is a miss, never another occurrence's answer."""
    copy_id = seed_keyed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [
            (CASE_A, 0, chat_body(), chat_response("a0"), 200),
            (CASE_A, 1, chat_body(), chat_response("a1"), 200),
        ],
    )

    def status_at(case_key: str, occurrence: int) -> int:
        response = authenticated_client.post(
            _replay_path(copy_id), json=chat_body(), headers=call_key(case_key, occurrence)
        )
        return response.status_code

    assert status_at(CASE_A, 2) == 404
    assert status_at(CASE_A, 9) == 404
    assert status_at(CASE_B, 0) == 404
    assert status_at(CASE_B, 1) == 404
    assert status_at("", 0) == 404


def test_replay_occurrence_header_is_gone(authenticated_client: TestClient) -> None:
    """The retired replay-occurrence header has no effect: only the key headers decide."""
    copy_id = seed_keyed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [
            (CASE_A, 0, chat_body(), chat_response("a0"), 200),
            (CASE_A, 1, chat_body(), chat_response("a1"), 200),
        ],
    )

    response = authenticated_client.post(
        _replay_path(copy_id),
        json=chat_body(),
        headers={**call_key(CASE_A, 0), "X-AIGW-Replay-Occurrence": "1"},
    )

    assert response.json()["id"] == "a0"


def _bad_key_headers() -> list[Any]:
    """Key-header sets that are not usable (design §4.2): a bad case key or occurrence."""
    ok_case = {CASE_KEY_HEADER: CASE_A}
    cases: list[Any] = [
        pytest.param({}, id="both-missing"),
        pytest.param(ok_case, id="occurrence-missing"),
    ]
    cases += [
        pytest.param({CASE_KEY_HEADER: "A" * 32, OCCURRENCE_HEADER: "0"}, id="uppercase-hex"),
        pytest.param({CASE_KEY_HEADER: "a" * 31, OCCURRENCE_HEADER: "0"}, id="31-chars"),
        pytest.param({CASE_KEY_HEADER: "a" * 33, OCCURRENCE_HEADER: "0"}, id="33-chars"),
        pytest.param({CASE_KEY_HEADER: "g" * 32, OCCURRENCE_HEADER: "0"}, id="non-hex"),
    ]
    cases += [
        pytest.param({**ok_case, OCCURRENCE_HEADER: value}, id=f"occurrence-{value!r}")
        for value in _BAD_OCCURRENCES
    ]
    return cases


@pytest.mark.parametrize("headers", _bad_key_headers())
def test_bad_or_missing_key_headers_are_a_400_malformed_call_key(
    authenticated_client: TestClient, headers: dict[str, str]
) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("a"), 200)],
    )
    encoded = {name: value.encode("utf-8") for name, value in headers.items()}

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body(), headers=encoded)

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "malformed_call_key"


def test_replay_of_a_request_that_was_never_captured_is_a_miss(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("a"), 200)],
    )

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(temperature=0.7), headers=call_key()
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_miss"
    assert "X-AIGW-Replay" not in response.headers


def test_a_tool_entry_is_not_an_answer_to_a_chat_request(
    authenticated_client: TestClient,
) -> None:
    """The digest covers the kind: the same JSON as a tool description is a chat miss."""
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("tool", chat_body(), {"result": "tool text"}, 200)],
    )

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key()
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_miss"


def test_replay_of_an_open_or_unknown_copy_is_404_unavailable(
    authenticated_client: TestClient,
) -> None:
    owner = account_id_of(authenticated_client)
    open_copy = seed_copy(
        authenticated_client,
        owner,
        [("chat", chat_body(), chat_response("a"), 200)],
        seal=False,
    )

    for copy_id in (open_copy, str(uuid4())):
        response = authenticated_client.post(
            _replay_path(copy_id), json=chat_body(), headers=call_key()
        )
        assert response.status_code == 404, copy_id
        detail = response.json()["detail"]
        assert detail["code"] == "frozen_copy_unavailable"
        assert isinstance(detail["message"], str)


def test_any_authenticated_account_may_replay_a_sealed_copy(
    authenticated_client: TestClient, provisioned_user_factory
) -> None:
    """Design Q16: whoever holds the id and sends the exact request may replay."""
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("a"), 200)],
    )
    provisioned_user_factory("replayer")
    login = authenticated_client.post(
        "/v1/auth/login", json={"username": "replayer", "password": "test-user-password"}
    )
    other = {"Authorization": f"Bearer {login.json()['token']}"}

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers={**other, **call_key()}
    )

    assert response.status_code == 200, response.text


def test_replay_requires_authentication(client: TestClient) -> None:
    response = client.post(_replay_path(str(uuid4())), json=chat_body())

    assert response.status_code in (401, 403)


def test_replay_body_reports_zero_cost_and_marks_frozen_copy_replay(
    authenticated_client: TestClient,
) -> None:
    """The captured body came from a PAID live call; the replay must account as a free hit.

    The engine reads `request_economics.direct_cost_status == "not_applicable"` together with
    `usage_accounting.cache.status == "hit"` as zero spend, so that is the shape asserted.
    """
    paid = {
        **chat_response("paid"),
        "_aigw": {
            "usage_accounting": {
                "schema": "aigw.usage-accounting.v1",
                "capture_status": "complete",
                "gateway_call_id": "gw-original",
                "cache": {"status": "miss", "reference": None},
                "observed_attempts": 1,
                "rendered_attempts": 1,
                "omitted_attempts": 0,
                "attempts": [{"attempt": 1}],
            },
            "request_economics": {
                "schema": "aigw.request-economics.v1",
                "observed_new_attempts": 1,
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [
                    {"amount": "0.5", "unit": "openrouter_credits", "source": "provider"}
                ],
            },
        },
    }
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), paid, 200)],
    )

    first = authenticated_client.post(_replay_path(copy_id), json=chat_body(), headers=call_key())
    second = authenticated_client.post(_replay_path(copy_id), json=chat_body(), headers=call_key())

    assert first.status_code == 200, first.text
    aigw = first.json()["_aigw"]
    assert aigw["frozen_copy_replay"] is True
    assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"
    assert aigw["request_economics"]["known_direct_cost_subtotals"] == []
    assert aigw["request_economics"]["observed_new_attempts"] == 0
    assert aigw["usage_accounting"]["cache"]["status"] == "hit"
    assert aigw["usage_accounting"]["attempts"] == []
    # The answer itself is untouched, and the stored row keeps its original cost evidence.
    assert first.json()["choices"] == paid["choices"]
    assert second.json()["_aigw"]["frozen_copy_replay"] is True


def test_a_captured_body_without_aigw_still_replays_with_the_zero_cost_block(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("bare"), 200)],
    )

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key()
    )

    aigw = response.json()["_aigw"]
    assert aigw["frozen_copy_replay"] is True
    assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"


def test_a_replayed_error_carries_the_zero_cost_block_beside_the_detail(
    authenticated_client: TestClient,
) -> None:
    detail = {"code": "provider_error", "message": "nope"}
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), {"detail": detail}, 502)],
    )

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers=call_key()
    )

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"detail", "_aigw"}
    assert body["detail"] == detail
    assert body["_aigw"]["frozen_copy_replay"] is True
    assert body["_aigw"]["request_economics"]["direct_cost_status"] == "not_applicable"
    assert response.headers["X-AIGW-Replay"] == "error"


def test_a_malformed_copy_id_on_replay_is_404_unavailable_not_422(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        _replay_path("not-a-uuid"), json=chat_body(), headers=call_key()
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_unavailable"
