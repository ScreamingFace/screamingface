from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.plugins.local_provider.settings import LocalPluginSettings


def test_local_provider_is_disabled_by_default() -> None:
    settings = LocalPluginSettings()

    assert settings.enabled is False
    assert str(settings.base_url) == "http://127.0.0.1:1234/v1"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/v1",
        "http://127.42.0.9:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_local_provider_accepts_numeric_loopback_v1_origins(base_url: str) -> None:
    assert str(LocalPluginSettings(enabled=True, base_url=base_url).base_url) == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:1234/v1",
        "http://192.168.1.2:1234/v1",
        "https://127.0.0.1:1234/v1",
        "http://user:password@127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/other",
        "http://127.0.0.1:1234/v1?target=other",
        "http://127.0.0.1:1234/v1#fragment",
    ],
)
def test_local_provider_refuses_non_loopback_or_noncanonical_targets(base_url: str) -> None:
    with pytest.raises(ValidationError):
        LocalPluginSettings(enabled=True, base_url=base_url)
