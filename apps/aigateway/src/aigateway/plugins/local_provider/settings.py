from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from aigateway.core.plugin_base import PluginSettings

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"


def normalize_local_base_url(value: str) -> str:
    # INVARIANT: a numeric loopback literal plus fixed `/v1` path is the complete
    # routing authority. DNS, credentials, query controls, and caller paths never enter.
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("local provider base URL is invalid") from exc
    if parsed.scheme != "http" or parsed.username is not None or parsed.password is not None:
        raise ValueError("local provider requires an unauthenticated HTTP loopback URL")
    if parsed.query or parsed.fragment or parsed.path != "/v1":
        raise ValueError("local provider base URL must end at /v1")
    if parsed.hostname is None or port is None:
        raise ValueError("local provider base URL requires a numeric loopback host and port")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("local provider base URL requires a numeric loopback host") from exc
    if not address.is_loopback:
        raise ValueError("local provider base URL requires a numeric loopback host")
    return urlunsplit(("http", parsed.netloc, "/v1", "", ""))


class LocalPluginSettings(PluginSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_LOCAL_",
        extra="ignore",
        populate_by_name=True,
    )

    # FEATURE: local model serving is explicit operator opt-in and default-off.
    enabled: bool = False
    base_url: str = DEFAULT_LOCAL_BASE_URL

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return normalize_local_base_url(value)
