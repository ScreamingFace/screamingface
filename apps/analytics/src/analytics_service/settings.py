"""Deployment-only configuration; disabled by default."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", extra="forbid")
    bridge_enabled: bool = False
    bridge_origin: str = ""
    bridge_parent_origins: str = ""
    bridge_ancestor_origins: str = ""
    bridge_cookie_max_age: int = Field(default=15552000, ge=86400, le=31536000)
    enabled: bool = False
    env: Literal["test", "production"] = "test"
    posthog_host: str = ""
    posthog_allowed_hosts: str = ""
    posthog_project_token: SecretStr = SecretStr("")
    max_inflight: int = Field(default=16, ge=1, le=1024)
    requests_per_minute: int = Field(default=120, ge=1, le=100000)
    host: str = "127.0.0.1"
    port: int = Field(default=9110, ge=1, le=65535)

    @model_validator(mode="after")
    def destination(self) -> Self:
        if not self.enabled:
            return self
        url = urlsplit(self.posthog_host)
        # WHY: urlsplit defers invalid-port validation until this property is read.
        _ = url.port
        allowed = {name.strip() for name in self.posthog_allowed_hosts.split(",")}
        safe = (
            url.scheme == "https"
            and url.hostname in allowed
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path in ("", "/")
        )
        if not safe or not self.posthog_project_token.get_secret_value().strip():
            raise ValueError(
                "enabled delivery requires an allowlisted HTTPS origin and project token"
            )
        return self

    @model_validator(mode="after")
    def bridge_configuration(self) -> Self:
        if self.bridge_enabled:
            origins = [self.bridge_origin]
            for field in (self.bridge_parent_origins, self.bridge_ancestor_origins):
                origins.extend(field.split(","))
            for origin in origins:
                validate_origin(origin.strip())
        return self


def validate_origin(origin: str) -> None:
    url = urlsplit(origin)
    _ = url.port
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
        or any(c in origin for c in "*; \n\r\t")
    ):
        raise ValueError("bridge requires exact HTTPS origins")
    if url.netloc != url.hostname and url.netloc != f"{url.hostname}:{url.port}":
        raise ValueError("invalid bridge origin")
