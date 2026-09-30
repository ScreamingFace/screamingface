from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite://./scoreboard.sqlite3"

AuthMode = Literal["disabled", "cloudflare_headers"]


def normalize_database_url(database_url: str) -> str:
    sqlite_absolute_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_absolute_prefix):
        return database_url

    path = database_url.removeprefix(sqlite_absolute_prefix)
    if not path or "/" in path:
        return database_url

    # Accept the common SQLite relative-file spelling instead of writing to /.
    return f"sqlite://./{path}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCOREBOARD_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 9106
    log_level: str = "info"
    database_url: str = DEFAULT_DATABASE_URL
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    portal_dir: Path | None = None
    portal_artifacts_dir: Path | None = None

    auth_mode: AuthMode = "disabled"
    """How ``POST /v1/scores`` establishes who is submitting.

    - ``disabled`` (default) — trust the client-supplied ``submitted_by`` free text, unchanged
      from today's behavior. Every existing deployment and test keeps working until this is
      explicitly opted into ``cloudflare_headers``.
    - ``cloudflare_headers`` — trust the identity header Envoy injects after re-verifying
      Cloudflare Access (:mod:`scoreboard.core.auth.cloudflare_identity`). Sound ONLY while this
      service is unreachable except through that chain — see ``allowed_networks``.

    AIDEV-NOTE: ``cloudflare_headers`` mode also depends on a setting that lives OUTSIDE this
    class — the ``FORWARDED_ALLOW_IPS`` env var uvicorn itself reads (no ``SCOREBOARD_`` prefix,
    not a pydantic field). It must not be ``"*"`` in this mode, or a client-supplied
    ``X-Forwarded-For`` can forge the peer address ``allowed_networks`` checks. Enforced in
    :func:`scoreboard.main.create_app`, not here — see that function's guard.
    """

    # WHY `NoDecode`: pydantic-settings JSON-decodes complex field types read from the
    # environment, so without it `SCOREBOARD_ALLOWED_NETWORKS=10.0.0.0/8` fails as malformed
    # JSON before the validator below ever runs. The value is a comma-separated list, not JSON.
    allowed_networks: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = Field(default=())
    """Peers that may present an identity header, as CIDR networks. Only read in
    ``cloudflare_headers`` mode, where it is mandatory — see
    :func:`scoreboard.core.auth.cloudflare_identity.peer_in_networks`.
    """

    clustering_enabled: bool = False
    """FEATURE: E14 — POST /v1/scores clusters by system (prd/submit-and-cluster.md).

    WHY the code default is False: the legacy route tests are append-only and pin one row per
    content hash (tests/unit/test_scores_routes.py:169-191). False keeps them meaningful. Unit
    WIRING (D6) turns it on in the chart and in the local runtime (`screamingface up`).
    """

    receipt_public_keys: dict[str, str] = Field(default_factory=dict)
    """C3 verifier keys: kid -> standard base64 of the RAW 32-byte Ed25519 public key (current
    plus previous). Env SCOREBOARD_RECEIPT_PUBLIC_KEYS, a JSON object. Public keys, not a secret.

    INVARIANT: the same encoding and the same kid values that the gateway publishes
    (GW-freeze.md OD-F2: kid = sha256(raw public key).hexdigest()[:16]) and that the local runtime
    writes (SDK-replay.md section 4.12). The scoreboard does not derive the kid; it uses the map
    keys as given.
    """

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, database_url: str) -> str:
        return normalize_database_url(database_url)

    @field_validator("allowed_networks", mode="before")
    @classmethod
    def _parse_allowed_networks(cls, value: object) -> object:
        """Parse the comma-separated CIDR list.

        `strict=True` deliberately: it rejects a value with host bits set (`192.168.0.0/8`)
        instead of widening it to the enclosing network, which would silently trust far more
        addresses than the operator named.
        """
        if not isinstance(value, str):
            return value
        return tuple(
            ip_network(entry, strict=True) for part in value.split(",") if (entry := part.strip())
        )
