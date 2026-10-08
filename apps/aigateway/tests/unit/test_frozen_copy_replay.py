"""Replay endpoints answer a sealed frozen copy and nothing else (OME-1307, design §4.4)."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.unit.test_frozen_copy_support import (
    PATCH_TARGET,
    DispatchCounter,
    account_id_of,
    chat_body,
    chat_response,
    seed_copy,
)

_OCCURRENCE = "X-AIGW-Replay-Occurrence"


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

    response = authenticated_client.post(_replay_path(copy_id), json=body)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "captured"
    assert response.headers["X-AIGW-Replay"] == "hit"
    assert forbidden == []
    assert dispatch.calls == []


def _lookup_cases() -> list[Any]:
    ok = lambda marker: ("chat", chat_body(), chat_response(marker), 200)  # noqa: E731
    err = lambda status, text: (  # noqa: E731
        "chat",
        chat_body(),
        {"detail": {"code": "provider_error", "message": text}},
        status,
    )
    return [
        pytest.param([ok("a"), ok("b"), ok("c")], 0, ("ok", "a"), id="first-success"),
        pytest.param([ok("a"), ok("b"), ok("c")], 1, ("ok", "b"), id="second-success"),
        pytest.param([ok("a"), ok("b"), ok("c")], 2, ("ok", "c"), id="last-success"),
        pytest.param([ok("a"), ok("b"), ok("c")], 9, ("ok", "c"), id="past-the-end-gives-last"),
        pytest.param(
            [err(429, "e1"), ok("a"), err(500, "e2"), ok("b")],
            1,
            ("ok", "b"),
            id="errors-do-not-count-as-occurrences",
        ),
        pytest.param(
            [err(429, "e1"), ok("a"), err(500, "e2")],
            0,
            ("ok", "a"),
            id="success-wins-over-errors",
        ),
        pytest.param(
            [err(503, "e1"), err(500, "e2")], 0, ("error", (500, "e2")), id="latest-error"
        ),
        pytest.param(
            [err(503, "e1"), err(500, "e2")], 7, ("error", (500, "e2")), id="latest-error-any-n"
        ),
    ]


@pytest.mark.parametrize(("entries", "occurrence", "expected"), _lookup_cases())
def test_replay_lookup_rule(
    authenticated_client: TestClient, entries: list[Any], occurrence: int, expected: tuple
) -> None:
    copy_id = seed_copy(authenticated_client, account_id_of(authenticated_client), entries)

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers={_OCCURRENCE: str(occurrence)}
    )

    kind, value = expected
    if kind == "ok":
        assert response.status_code == 200, response.text
        assert response.json()["id"] == value
        assert response.headers["X-AIGW-Replay"] == "hit"
    else:
        status, message = value
        assert response.status_code == status
        assert response.json()["detail"] == {"code": "provider_error", "message": message}
        assert response.headers["X-AIGW-Replay"] == "error"


def test_replay_occurrence_defaults_to_the_first_success(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response(m), 200) for m in ("a", "b")],
    )

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body())

    assert response.json()["id"] == "a"


def test_replay_of_a_request_that_was_never_captured_is_a_miss(
    authenticated_client: TestClient,
) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("a"), 200)],
    )

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body(temperature=0.7))

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

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_miss"


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", ""])
def test_a_malformed_occurrence_is_a_400(authenticated_client: TestClient, value: str) -> None:
    copy_id = seed_copy(
        authenticated_client,
        account_id_of(authenticated_client),
        [("chat", chat_body(), chat_response("a"), 200)],
    )

    response = authenticated_client.post(
        _replay_path(copy_id), json=chat_body(), headers={_OCCURRENCE: value}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "malformed_replay_occurrence"


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
        response = authenticated_client.post(_replay_path(copy_id), json=chat_body())
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

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body(), headers=other)

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

    first = authenticated_client.post(_replay_path(copy_id), json=chat_body())
    second = authenticated_client.post(_replay_path(copy_id), json=chat_body())

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

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body())

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

    response = authenticated_client.post(_replay_path(copy_id), json=chat_body())

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
    response = authenticated_client.post(_replay_path("not-a-uuid"), json=chat_body())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "frozen_copy_unavailable"
