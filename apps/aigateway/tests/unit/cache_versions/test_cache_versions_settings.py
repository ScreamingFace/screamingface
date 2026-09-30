"""Support: the freeze settings and their wiring (OME-1307, GW-freeze).

FEATURE: OME-1307 (E14) - startup validation of the archive backend, and what the composition
builds for each combination of the kill switch, the signing key and the backend.
INVARIANT: a missing signing key never stops capture, and no key value reaches a log or a message.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from aigateway.config import Settings
from aigateway.core.cache_versions.archive_store import (
    FilesystemVersionArchiveStore,
    S3VersionArchiveStore,
)
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.cache_versions.wiring import build_cache_version_services
from tests.unit.cache_versions.conftest import raw_private_b64


def _settings(**values: object) -> Settings:
    return Settings(**{"_env_file": None, **values})


def test_freeze_defaults() -> None:
    settings = _settings()

    assert settings.receipt_signing_key is None
    assert settings.cache_version_max_entries == 20_000
    assert settings.cache_version_max_archive_bytes == 1_500_000_000
    assert settings.cache_version_archive_backend == "none"
    assert settings.cache_version_s3_bucket == "screamingface-cache-versions"
    assert settings.cache_version_s3_region == "garage"
    assert settings.cache_version_s3_timeout_s == 120.0
    assert settings.cache_version_export_poll_s == 30.0


def test_the_flag_on_without_a_key_does_not_refuse_startup() -> None:
    # WHY: the GW-capture tests switch the flag on with no key. Startup must accept that.
    assert _settings(AIGW_CACHE_VERSIONS_ENABLED="true").receipt_signing_key is None


@pytest.mark.parametrize(
    "name", ["AIGW_CACHE_VERSION_MAX_ENTRIES", "AIGW_CACHE_VERSION_MAX_ARCHIVE_BYTES"]
)
def test_a_cap_must_be_positive(name: str) -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        _settings(**{name: "0"})


def test_s3_without_its_storage_names_every_missing_variable() -> None:
    with pytest.raises(ValueError) as excinfo:
        _settings(AIGW_CACHE_VERSION_ARCHIVE_BACKEND="s3")

    for name in (
        "AIGW_CACHE_VERSION_S3_ENDPOINT_URL",
        "AIGW_CACHE_VERSION_S3_ACCESS_KEY",
        "AIGW_CACHE_VERSION_S3_SECRET_KEY",
    ):
        assert name in str(excinfo.value)


def test_s3_with_partial_storage_names_only_what_is_missing() -> None:
    with pytest.raises(ValueError) as excinfo:
        _settings(
            AIGW_CACHE_VERSION_ARCHIVE_BACKEND="s3",
            AIGW_CACHE_VERSION_S3_ENDPOINT_URL="http://garage:3900",
            AIGW_CACHE_VERSION_S3_ACCESS_KEY="GKaccess",
            AIGW_CACHE_VERSION_S3_SECRET_KEY="  ",
        )

    text = str(excinfo.value)
    assert "AIGW_CACHE_VERSION_S3_SECRET_KEY" in text
    assert "AIGW_CACHE_VERSION_S3_ENDPOINT_URL" not in text
    assert "GKaccess" not in text


def test_filesystem_without_a_directory_is_refused() -> None:
    with pytest.raises(ValueError, match="AIGW_CACHE_VERSION_ARCHIVE_DIR"):
        _settings(AIGW_CACHE_VERSION_ARCHIVE_BACKEND="filesystem")


def test_an_unknown_backend_is_refused() -> None:
    with pytest.raises(ValueError, match="AIGW_CACHE_VERSION_ARCHIVE_BACKEND|archive_backend"):
        _settings(AIGW_CACHE_VERSION_ARCHIVE_BACKEND="gcs")


def test_s3_with_full_storage_parses() -> None:
    settings = _settings(
        AIGW_CACHE_VERSION_ARCHIVE_BACKEND="s3",
        AIGW_CACHE_VERSION_S3_ENDPOINT_URL="http://garage:3900",
        AIGW_CACHE_VERSION_S3_ACCESS_KEY="GKaccess",
        AIGW_CACHE_VERSION_S3_SECRET_KEY="s3cr3t-value-xyz",
    )

    assert settings.cache_version_s3_access_key == SecretStr("GKaccess")
    assert "s3cr3t-value-xyz" not in repr(settings)


def _wire(**values: object):
    stats = CaptureStats()
    return build_cache_version_services(_settings(**values), stats), stats


def test_wiring_with_the_flag_off_builds_nothing() -> None:
    services, _ = _wire(AIGATEWAY_RECEIPT_SIGNING_KEY=raw_private_b64(Ed25519PrivateKey.generate()))

    assert (services.freezer, services.exporter) == (None, None)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_flag_on_without_a_key_logs_a_warning_and_builds_nothing(
    blank: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    values: dict[str, object] = {"AIGW_CACHE_VERSIONS_ENABLED": "true"}
    if blank is not None:
        values["AIGATEWAY_RECEIPT_SIGNING_KEY"] = blank

    with caplog.at_level(logging.WARNING):
        services, _ = _wire(**values)

    assert (services.freezer, services.exporter) == (None, None)
    assert "capture on, freeze off (AIGATEWAY_RECEIPT_SIGNING_KEY is not set)" in caplog.text


def test_a_bad_key_fails_at_wiring_without_the_value(caplog: pytest.LogCaptureFixture) -> None:
    bad = base64.b64encode(b"too short to be a key").decode()

    with pytest.raises(RuntimeError) as excinfo, caplog.at_level(logging.DEBUG):
        _wire(AIGW_CACHE_VERSIONS_ENABLED="true", AIGATEWAY_RECEIPT_SIGNING_KEY=bad)

    assert bad not in str(excinfo.value)
    assert bad not in caplog.text


def test_a_good_key_builds_the_freezer_and_logs_only_the_public_kid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = raw_private_b64(Ed25519PrivateKey.generate())

    with caplog.at_level(logging.INFO):
        services, _ = _wire(AIGW_CACHE_VERSIONS_ENABLED="true", AIGATEWAY_RECEIPT_SIGNING_KEY=key)

    assert isinstance(services.freezer, FreezeService)
    assert services.exporter is None, "the default backend is none"
    assert "cache version receipts ready kid=" in caplog.text
    assert key not in caplog.text


def test_a_backend_builds_an_exporter_that_the_freezer_wakes(tmp_path: Path) -> None:
    key = raw_private_b64(Ed25519PrivateKey.generate())

    services, _ = _wire(
        AIGW_CACHE_VERSIONS_ENABLED="true",
        AIGATEWAY_RECEIPT_SIGNING_KEY=key,
        AIGW_CACHE_VERSION_ARCHIVE_BACKEND="filesystem",
        AIGW_CACHE_VERSION_ARCHIVE_DIR=str(tmp_path),
    )

    assert services.exporter is not None
    assert isinstance(services.exporter._archive, FilesystemVersionArchiveStore)
    assert services.freezer is not None


def test_the_s3_backend_builds_the_s3_store() -> None:
    key = raw_private_b64(Ed25519PrivateKey.generate())

    services, _ = _wire(
        AIGW_CACHE_VERSIONS_ENABLED="true",
        AIGATEWAY_RECEIPT_SIGNING_KEY=key,
        AIGW_CACHE_VERSION_ARCHIVE_BACKEND="s3",
        AIGW_CACHE_VERSION_S3_ENDPOINT_URL="http://garage:3900",
        AIGW_CACHE_VERSION_S3_ACCESS_KEY="GKaccess",
        AIGW_CACHE_VERSION_S3_SECRET_KEY="secret",
    )

    assert services.exporter is not None
    assert isinstance(services.exporter._archive, S3VersionArchiveStore)
