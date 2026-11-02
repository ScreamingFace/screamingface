import logging

import pytest
from fastapi.testclient import TestClient

from aigateway.config import Settings
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


# WHY no startup-import tests (OME-1209 E4b): the opt-in Claude Code import and the plugins'
# `bootstrap_profiles` hook are retired; `test_profile_index_offline_only.py`
# (`test_no_module_reads_the_retired_bootstrap_flag`) pins that nothing reads the flag, whose
# warning retired in the OME-1138 close-out, L4a.


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
