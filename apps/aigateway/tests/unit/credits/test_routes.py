from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.auth.middleware import current_account
from aigateway.core.credits import CreditStatus, unavailable
from aigateway.core.endpoint_access import PERMIT_ALL
from aigateway.core.provider_access import Authorization, CredentialTarget
from aigateway.routes.credits import router


def app_and_service():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_account] = lambda: SimpleNamespace(id="caller-a")
    app.state.endpoint_access = PERMIT_ALL
    app.state.providers = SimpleNamespace(get=lambda provider: object())
    target = CredentialTarget("stored", "api_key", "chosen", "context", None)
    app.state.provider_access = SimpleNamespace(
        resolve=AsyncMock(return_value=target),
        authorize=AsyncMock(
            return_value=Authorization(
                {"Authorization": "Bearer selected-secret"}, "chosen", "api_key"
            )
        ),
    )
    service = SimpleNamespace(
        supports=lambda p: p == "openrouter",
        read=AsyncMock(
            return_value=CreditStatus(
                provider="openrouter",
                account=unavailable("management_key_required"),
                key=unavailable("lookup_failed"),
            )
        ),
        configure=AsyncMock(),
        remove=AsyncMock(),
    )
    app.state.credits = service
    return app, service


def test_read_uses_caller_and_execution_credential_without_exposing_it():
    app, service = app_and_service()
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter")
    assert response.status_code == 200
    assert response.json() == service.read.return_value.model_dump(mode="json")
    assert response.headers["cache-control"] == "private, no-store"
    service.read.assert_awaited_once_with("caller-a", "openrouter", "selected-secret", refresh=True)


def test_management_key_write_and_removal_are_caller_scoped():
    app, service = app_and_service()
    with TestClient(app) as client:
        response = client.put(
            "/v1/credits/openrouter/management-key", json={"api_key": "management-secret"}
        )
        removed = client.delete("/v1/credits/openrouter/management-key")
    assert response.status_code == removed.status_code == 204
    assert not response.content
    service.configure.assert_awaited_once_with(
        "caller-a", "openrouter", "selected-secret", "management-secret"
    )
    service.remove.assert_awaited_once_with("caller-a", "openrouter")


def test_invalid_management_body_never_echoes_input():
    app, service = app_and_service()
    with TestClient(app) as client:
        response = client.put(
            "/v1/credits/openrouter/management-key", json={"api_key": {"secret": "never-echo"}}
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid credit request"}
    service.configure.assert_not_awaited()


def test_retired_selector_is_refused_before_credential_read():
    app, service = app_and_service()
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter", headers={"X-Profile": "other"})
    assert response.status_code == 400
    app.state.provider_access.resolve.assert_not_awaited()
    service.read.assert_not_awaited()


def test_connection_changed_during_lookup_discards_old_balance():
    app, service = app_and_service()
    app.state.provider_access.authorize.side_effect = [
        Authorization({"Authorization": "Bearer old"}, "chosen", "api_key"),
        Authorization({"Authorization": "Bearer new"}, "chosen", "api_key"),
    ]
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter")
    assert response.status_code == 409
    assert response.json() == {"detail": "Provider connection changed during credit lookup"}


def test_key_only_route_uses_the_authenticated_execution_connection():
    app, service = app_and_service()
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter/key", params={"refresh": "false"})
    assert response.status_code == 200
    service.read.assert_awaited_once_with(
        "caller-a", "openrouter", "selected-secret", refresh=False, include_account=False
    )
    assert response.headers["cache-control"] == "private, no-store"


def test_key_only_route_refuses_anonymous_shared_principal():
    from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID

    app, service = app_and_service()
    app.dependency_overrides[current_account] = lambda: SimpleNamespace(id=ANONYMOUS_ACCOUNT_ID)
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter/key")
    assert response.status_code == 401
    service.read.assert_not_awaited()
    app.state.provider_access.resolve.assert_not_awaited()


def test_hosted_key_allowance_does_not_authorize_an_ambient_credential():
    app, service = app_and_service()
    app.state.provider_access.resolve.return_value = CredentialTarget(
        "ambient", "api_key", None, "ambient", None
    )
    with TestClient(app) as client:
        response = client.get("/v1/credits/openrouter/key")
    assert response.status_code == 200
    app.state.provider_access.authorize.assert_not_awaited()
    service.read.assert_awaited_once_with(
        "caller-a", "openrouter", None, refresh=True, include_account=False
    )
