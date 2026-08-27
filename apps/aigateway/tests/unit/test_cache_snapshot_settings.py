"""Settings evidence for the cache-snapshot schedule (OME-1021).

The feature is opt-in and its storage is mandatory when enabled — both enforced at
construction (the startup path), so a misconfigured deployment fails loudly instead of
bootstrapping a snapshot that silently does nothing every Friday.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from aigateway.config import Settings


def _settings(**values: object) -> Settings:
    return Settings(**{"_env_file": None, **values})


def test_snapshot_defaults_are_opt_in() -> None:
    settings = _settings()
    assert settings.cache_snapshot_enabled is False
    assert settings.cache_snapshot_cron == "0 5 * * 5"
    assert settings.cache_snapshot_s3_bucket == "screamingface-cache-snapshots"
    assert settings.cache_snapshot_s3_region == "garage"
    assert settings.cache_snapshot_s3_endpoint_url is None
    assert settings.cache_snapshot_s3_access_key is None


def test_an_unsupported_schedule_is_refused() -> None:
    with pytest.raises(ValueError, match="AIGW_CACHE_SNAPSHOT_CRON"):
        _settings(AIGW_CACHE_SNAPSHOT_CRON="0 0 * * 1")


def test_enabled_without_storage_is_refused() -> None:
    with pytest.raises(ValueError, match="storage is not configured"):
        _settings(AIGW_CACHE_SNAPSHOT_ENABLED="true")


def test_enabled_with_partial_storage_is_refused() -> None:
    with pytest.raises(ValueError, match="AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY"):
        _settings(
            AIGW_CACHE_SNAPSHOT_ENABLED="true",
            AIGW_CACHE_SNAPSHOT_S3_ENDPOINT_URL="http://garage:3900",
            AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY="secret",
        )


def test_enabled_with_full_storage_parses() -> None:
    settings = _settings(
        AIGW_CACHE_SNAPSHOT_ENABLED="true",
        AIGW_CACHE_SNAPSHOT_S3_ENDPOINT_URL="http://127.0.0.1:3900",
        AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY="GKtestaccess",
        AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY="secret",
        AIGW_CACHE_SNAPSHOT_TIMEOUT_S="120",
    )
    assert settings.cache_snapshot_enabled is True
    assert settings.cache_snapshot_s3_access_key == SecretStr("GKtestaccess")
    assert settings.cache_snapshot_timeout_s == 120.0
    # The restore contract: equal to cache_upload_max_bytes by default (both count the
    # compressed archive), so a published snapshot always fits the admin upload cap.
    assert settings.cache_snapshot_max_bytes == 256 * 1024 * 1024
    assert settings.cache_snapshot_max_bytes == settings.cache_upload_max_bytes


def test_an_export_cap_above_the_restore_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="AIGW_CACHE_UPLOAD_MAX_BYTES"):
        _settings(
            AIGW_CACHE_SNAPSHOT_ENABLED="true",
            AIGW_CACHE_SNAPSHOT_S3_ENDPOINT_URL="http://127.0.0.1:3900",
            AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY="GKtestaccess",
            AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY="secret",
            AIGW_CACHE_SNAPSHOT_MAX_BYTES=str(300 * 1024 * 1024),
        )


def test_caps_raised_together_parse() -> None:
    settings = _settings(
        AIGW_CACHE_SNAPSHOT_ENABLED="true",
        AIGW_CACHE_SNAPSHOT_S3_ENDPOINT_URL="http://127.0.0.1:3900",
        AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY="GKtestaccess",
        AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY="secret",
        AIGW_CACHE_UPLOAD_MAX_BYTES=str(512 * 1024 * 1024),
        AIGW_CACHE_SNAPSHOT_MAX_BYTES=str(512 * 1024 * 1024),
    )
    assert settings.cache_snapshot_max_bytes == 512 * 1024 * 1024


def test_the_cap_invariant_is_not_enforced_when_snapshots_are_disabled() -> None:
    """With the feature off, the export cap is inert — a mismatched pair must not block boot."""
    settings = _settings(AIGW_CACHE_SNAPSHOT_MAX_BYTES=str(512 * 1024 * 1024))
    assert settings.cache_snapshot_max_bytes == 512 * 1024 * 1024
