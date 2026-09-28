"""Stage D: explicit ``X-Profile`` is rejected at AIGateway ingress (OME-1394)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.provider_access import SelectorAmbiguous, SelectorUnsupported
from aigateway.routes.provider_access_http import render_refusal

_MODEL = "anthropic/claude-opus-4-8"
_UNSUPPORTED_MESSAGE = "X-Profile is no longer supported; omit the header."
_AMBIGUOUS_MESSAGE = "Multiple active Connections exist. Remove extra Connections, then retry."


@dataclass(frozen=True)
class _RequestCase:
    name: str
    method: str
    path: str
    kwargs: dict[str, Any]


_REQUEST_CASES = (
    _RequestCase(
        "chat",
        "post",
        "/v1/chat/completions",
        {"json": {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}},
    ),
    _RequestCase(
        "chat_stream",
        "post",
        "/v1/chat/completions",
        {
            "json": {
                "model": _MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            }
        },
    ),
    _RequestCase(
        "model_parameters",
        "get",
        "/v1/model-parameters",
        {"params": {"model": _MODEL}},
    ),
    _RequestCase(
        "model_admission",
        "post",
        "/v1/models/admit",
        {"json": {"model_id": _MODEL}},
    ),
    _RequestCase("provider_access", "get", "/v1/provider-access", {}),
)


class _RecordingAccess:
    """Transparent port proxy proving an explicit selector is refused before port I/O."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.resolve_calls = 0
        self.availability_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def resolve(self, *args: Any, **kwargs: Any) -> Any:
        self.resolve_calls += 1
        return await self.delegate.resolve(*args, **kwargs)

    async def availability(self, *args: Any, **kwargs: Any) -> Any:
        self.availability_calls += 1
        return await self.delegate.availability(*args, **kwargs)


def _request(client: TestClient, case: _RequestCase, selector: str):
    return client.request(
        case.method,
        case.path,
        headers={"X-Profile": selector},
        **case.kwargs,
    )


@pytest.mark.parametrize("selector", ["default", "private-selector-value"])
@pytest.mark.parametrize("case", _REQUEST_CASES, ids=lambda case: case.name)
def test_explicit_selector_is_value_free_400_before_provider_access(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: _RequestCase,
    selector: str,
) -> None:
    app = cast(FastAPI, authenticated_client.app)
    access = _RecordingAccess(app.state.provider_access)
    monkeypatch.setattr(app.state, "provider_access", access)
    caplog.set_level(logging.DEBUG)

    response = _request(authenticated_client, case, selector)

    assert access.resolve_calls == 0
    assert access.availability_calls == 0
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "x_profile_unsupported",
        "message": _UNSUPPORTED_MESSAGE,
    }
    assert selector not in response.text
    assert selector not in caplog.text


@pytest.mark.parametrize("selector", [None, "", " ", "\t  \n"])
def test_absent_or_blank_selector_remains_selectorless(
    authenticated_client: TestClient, selector: str | None
) -> None:
    headers = {} if selector is None else {"X-Profile": selector}

    response = authenticated_client.get("/v1/provider-access", headers=headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "x-profile" not in response.headers.get("vary", "").lower()


def test_selector_unsupported_renderer_does_not_retain_the_value() -> None:
    selector = "private-selector-value"

    response = render_refusal(SelectorUnsupported())

    assert response.status_code == 400
    assert response.detail == {
        "code": "x_profile_unsupported",
        "message": _UNSUPPORTED_MESSAGE,
    }
    assert selector not in repr(response.detail)


def test_connection_ambiguous_guidance_has_no_rejected_escape_hatch() -> None:
    response = render_refusal(SelectorAmbiguous("anthropic"))

    assert response.status_code == 409
    assert response.detail == {
        "code": "connection_ambiguous",
        "provider": "anthropic",
        "message": _AMBIGUOUS_MESSAGE,
    }
    detail = cast(dict[str, Any], response.detail)
    assert "profile" not in detail["message"].lower()


@pytest.mark.parametrize(
    ("path", "params", "status"),
    [
        ("/v1/model-parameters", {"model": _MODEL}, 200),
        ("/v1/model-parameters", {"model": "bogus/model"}, 400),
    ],
)
def test_model_parameters_vary_only_by_authorization_after_sunset(
    authenticated_client: TestClient,
    path: str,
    params: dict[str, str],
    status: int,
) -> None:
    response = authenticated_client.get(path, params=params)

    assert response.status_code == status
    assert response.headers["cache-control"] == "private, no-store"
    assert {part.strip().lower() for part in response.headers["vary"].split(",")} == {
        "authorization"
    }


@pytest.mark.parametrize("case", _REQUEST_CASES, ids=lambda case: case.name)
def test_blank_first_header_cannot_hide_a_named_second_value(
    authenticated_client: TestClient,
    case: _RequestCase,
) -> None:
    selector = "private-selector-value"

    response = authenticated_client.request(
        case.method,
        case.path,
        headers=[("X-Profile", ""), ("X-Profile", selector)],
        **case.kwargs,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "x_profile_unsupported",
        "message": _UNSUPPORTED_MESSAGE,
    }
    assert selector not in response.text


def test_chat_refuses_explicit_selector_before_cache_lookup(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from aigateway.routes import chat as chat_route

    cache_lookup = AsyncMock(side_effect=AssertionError("cache lookup must not run"))
    monkeypatch.setattr(chat_route, "look_up_global_cache", cache_lookup)

    response = authenticated_client.post(
        "/v1/chat/completions",
        headers={"X-Profile": "default"},
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 400
    cache_lookup.assert_not_awaited()


@pytest.mark.parametrize("blank", ["", " ", "\t"])
@pytest.mark.parametrize("case", _REQUEST_CASES, ids=lambda case: case.name)
def test_blank_selector_is_not_rejected_on_any_route(
    authenticated_client: TestClient,
    case: _RequestCase,
    blank: str,
) -> None:
    response = authenticated_client.request(
        case.method,
        case.path,
        headers={"X-Profile": blank},
        **case.kwargs,
    )

    expected_status = {
        "chat": 404,
        "chat_stream": 404,
        "model_parameters": 200,
        "model_admission": 200,
        "provider_access": 200,
    }[case.name]
    assert response.status_code == expected_status, response.text
    detail = response.json().get("detail")
    assert detail != {
        "code": "x_profile_unsupported",
        "message": _UNSUPPORTED_MESSAGE,
    }


def test_authentication_precedes_repeated_selector_refusal(client: TestClient) -> None:
    response = client.get(
        "/v1/provider-access",
        headers=[("X-Profile", ""), ("X-Profile", "private-selector-value")],
    )

    assert response.status_code == 401
