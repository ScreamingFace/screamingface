import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.config import Settings
from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.profile_index import ProfileIndexStore
from tests.conftest import _prepare_sqlite_db


def _configure_app_db(
    monkeypatch, tmp_path, *, admin_password: str | None = "test-admin-password"
) -> str:
    database_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    if admin_password is None:
        monkeypatch.delenv("AIGATEWAY_ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", admin_password)
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    _prepare_sqlite_db(database_url)
    return database_url


def _settings_without_dotenv(database_url: str, *, auth_enabled: bool = True) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "database_url": database_url,
            "jwt_secret": "x" * 32,
            "provisioning_token": "p" * 32,
            "admin_password": None,
            "auth_enabled": auth_enabled,
        }
    )


def _auth_header(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


class _BootstrapSpyPlugin(ProviderPluginBase):
    custom_llm_provider = "spy"

    def __init__(self, bootstrap_mock) -> None:
        self.bootstrap_mock = bootstrap_mock

    def register_models(self) -> list[ModelEntry]:
        return []

    async def bootstrap_profiles(self, **kwargs: Any) -> None:
        await self.bootstrap_mock(**kwargs)


def _install_bootstrap_spy(monkeypatch, main_module, bootstrap_mock) -> None:
    def _load_plugins(registry) -> None:
        registry.register(_BootstrapSpyPlugin(bootstrap_mock))

    monkeypatch.setattr(main_module, "load_plugins", _load_plugins)


def test_lifespan_skips_bootstrap_by_default(monkeypatch, tmp_path) -> None:
    """When AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE is unset, _lifespan does not call bootstrap."""
    from unittest.mock import AsyncMock

    monkeypatch.delenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE", raising=False)
    _configure_app_db(monkeypatch, tmp_path)

    from aigateway import main as main_module

    mock_bootstrap = AsyncMock()
    _install_bootstrap_spy(monkeypatch, main_module, mock_bootstrap)

    app = main_module.create_app()
    with TestClient(app) as client:
        # WHY: the Profile listing route answers 410 since OME-1209 Stage E3; `/v1/auth/me`
        # drives the lifespan, and the caller's index slice is what the listing rendered.
        resp = client.get("/v1/auth/me", headers=_auth_header(client))
        assert resp.status_code == 200
        index: ProfileIndexStore = app.state.profile_index
        portal = client.portal
        assert portal is not None  # `with TestClient(...)` opened it
        assert portal.call(index.list, resp.json()["id"]) == []

    assert mock_bootstrap.call_count == 0


def test_lifespan_runs_bootstrap_when_env_set(monkeypatch, tmp_path) -> None:
    """When AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1, _lifespan calls bootstrap."""
    from unittest.mock import AsyncMock

    monkeypatch.setenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE", "1")
    _configure_app_db(monkeypatch, tmp_path)

    from aigateway import main as main_module

    mock_bootstrap = AsyncMock()
    _install_bootstrap_spy(monkeypatch, main_module, mock_bootstrap)

    app = main_module.create_app()
    with TestClient(app) as client:
        client.get("/v1/auth/me", headers=_auth_header(client))

    assert mock_bootstrap.call_count == 1
    assert mock_bootstrap.call_args.kwargs["account_id"]


def test_lifespan_bootstraps_disabled_auth_under_anonymous_account(monkeypatch, tmp_path) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setenv("AIGATEWAY_AUTH_ENABLED", "0")
    monkeypatch.setenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE", "1")
    _configure_app_db(monkeypatch, tmp_path)

    from aigateway import main as main_module

    mock_bootstrap = AsyncMock()
    _install_bootstrap_spy(monkeypatch, main_module, mock_bootstrap)

    app = main_module.create_app()
    with TestClient(
        app,
        base_url="http://127.0.0.1:9105",
        client=("127.0.0.1", 50000),
    ) as client:
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 200

    assert mock_bootstrap.call_count == 1
    assert mock_bootstrap.call_args.kwargs["account_id"] == str(ANONYMOUS_ACCOUNT_ID)


def test_lifespan_auth_enabled_requires_configured_admin_password(monkeypatch, tmp_path) -> None:
    database_url = _configure_app_db(monkeypatch, tmp_path, admin_password=None)

    from aigateway import main as main_module

    settings = _settings_without_dotenv(database_url)
    assert settings.admin_password is None
    app = main_module.create_app(settings)
    with pytest.raises(RuntimeError, match="AIGATEWAY_ADMIN_PASSWORD"):
        with TestClient(app):
            pass


def test_lifespan_auth_disabled_without_admin_password_does_not_log_secret(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    monkeypatch.setenv("AIGATEWAY_AUTH_ENABLED", "0")
    database_url = _configure_app_db(monkeypatch, tmp_path, admin_password=None)

    from aigateway import main as main_module

    settings = _settings_without_dotenv(database_url, auth_enabled=False)
    assert settings.admin_password is None
    assert settings.auth_enabled is False
    app = main_module.create_app(settings)
    # Capture at DEBUG so a re-introduced bootstrap-password log at ANY level
    # (not just WARNING+) is caught by the negative assertion below (SF-327 R2/F4).
    with caplog.at_level(logging.DEBUG):
        with TestClient(
            app,
            base_url="http://127.0.0.1:9105",
            client=("127.0.0.1", 50000),
        ) as client:
            resp = client.get("/v1/auth/me")

    assert resp.status_code == 200
    assert not any("Bootstrap admin password" in record.getMessage() for record in caplog.records)
