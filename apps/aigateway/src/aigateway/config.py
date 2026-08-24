from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AuthMode = Literal["jwt", "cloudflare_headers", "disabled"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIGW_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = 9105
    log_level: str = "info"
    database_url: SecretStr = Field(
        default=SecretStr("sqlite://./aigateway.sqlite3"),
        validation_alias="AIGATEWAY_DATABASE_URL",
    )
    jwt_secret: SecretStr | None = Field(default=None, validation_alias="AIGATEWAY_JWT_SECRET")
    admin_password: SecretStr | None = Field(
        default=None, validation_alias="AIGATEWAY_ADMIN_PASSWORD"
    )
    provisioning_token: SecretStr | None = Field(
        default=None, validation_alias="AIGATEWAY_PROVISIONING_TOKEN"
    )
    auth_enabled: bool = Field(default=True, validation_alias="AIGATEWAY_AUTH_ENABLED")
    """LEGACY. Supplies the default for :attr:`auth_mode`; new deployments set the mode directly."""

    auth_mode: AuthMode = Field(default="jwt", validation_alias="AIGW_AUTH_MODE")
    """How the gateway establishes who is calling. The single source of truth in code.

    - ``jwt`` — verify the gateway's own bearer token (the historical behavior).
    - ``cloudflare_headers`` — trust the identity header Envoy injects after re-verifying
      Cloudflare Access's assertion (:mod:`aigateway.core.auth.cloudflare_identity`). Sound ONLY
      while this port is unreachable except through that chain.
    - ``disabled`` — every caller is anonymous. Loopback-only, enforced by
      :class:`AuthDisabledLocalOnlyMiddleware`.

    WHY a mode rather than a second boolean: with ``auth_enabled`` plus a hypothetical
    ``trust_headers`` flag, "false/false" would mean authenticate-nobody-and-trust-nothing — a
    configuration that reads like the safe one and is in fact the most permissive. Three named
    states make "trust everything" unreachable by accident.
    """
    # WHY `NoDecode`: pydantic-settings JSON-decodes complex field types read from the environment,
    # so without it `AIGW_ALLOWED_NETWORKS=10.0.0.0/8` fails as malformed JSON before the validator
    # below ever runs. The value is a comma-separated list, not JSON.
    allowed_networks: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = Field(
        default=(), validation_alias="AIGW_ALLOWED_NETWORKS"
    )
    """Peers that may present an identity header, as CIDR networks. Only read in
    ``cloudflare_headers`` mode, where it is mandatory.

    INVARIANT: this is defence in depth BEHIND the deployment's NetworkPolicy, and the only half of
    that pair which cannot be declined — a NetworkPolicy restricts nothing unless the cluster's CNI
    enforces it, and where it does not, `X-User-Email` alone would let any reachable caller become
    any principal.
    """

    # WHY `NoDecode`: same trap as `allowed_networks` above — pydantic-settings would JSON-decode
    # this before the validator runs, so `AIGATEWAY_ADMIN_EMAILS=a@x,b@y` would fail as malformed
    # JSON. The value is a comma-separated list, not JSON.
    admin_emails: Annotated[frozenset[str], NoDecode] = Field(
        default=frozenset(), validation_alias="AIGATEWAY_ADMIN_EMAILS"
    )
    """Addresses allowed to reach ``/v1/admin``. Empty (the default) disables that API entirely.

    WHY a second gate on top of identity: `cloudflare_headers` mode makes EVERY caller who clears
    Cloudflare Access an ordinary `Account`. That is right for the inference surface and wrong for
    an administrative one, where a caller reads and mutates OTHER accounts' credentials.

    INVARIANT: membership here grants no account. An admin is not a tenant — see
    :mod:`aigateway.core.auth.admin`.
    """

    jwt_ttl_seconds: int = Field(default=86_400, validation_alias="AIGATEWAY_JWT_TTL_SECONDS")
    public_url: str | None = Field(default=None, validation_alias="AIGATEWAY_PUBLIC_URL")

    # Encryption-at-rest for credential_blobs (SF-221). secret_key is the master
    # key for the default `local` AES-GCM provider; when unset in local dev it is
    # auto-generated and persisted in the secret_master_keys table. Multi-worker /
    # hosted deployments MUST set AIGATEWAY_SECRET_KEY so every worker shares one key.
    #
    # Content (base64 + exactly-32-bytes) is intentionally NOT validated here: a
    # field_validator that raises would let Pydantic capture the rejected key in
    # the ValidationError (input_value=), leaking it into startup logs despite the
    # SecretStr type. The single source of truth for key validation is
    # ``secrets.master_key._decode_key``, which runs at startup (in the lifespan,
    # for the providers that actually use the key) and raises a clean RuntimeError
    # that never echoes the value.
    secret_key: SecretStr | None = Field(default=None, validation_alias="AIGATEWAY_SECRET_KEY")
    secret_provider: str = Field(default="local", validation_alias="AIGATEWAY_SECRET_PROVIDER")

    retry_max_attempts: int = Field(default=3, validation_alias="AIGW_RETRY_MAX_ATTEMPTS")
    retry_backoff_base_seconds: float = Field(
        default=0.5, validation_alias="AIGW_RETRY_BACKOFF_BASE"
    )
    retry_backoff_max_seconds: float = Field(default=8.0, validation_alias="AIGW_RETRY_BACKOFF_MAX")
    retry_max_total_wait_seconds: float = Field(
        default=30.0, validation_alias="AIGW_RETRY_MAX_WAIT"
    )
    retry_jitter_seconds: float = Field(default=0.25, validation_alias="AIGW_RETRY_JITTER")
    provider_max_concurrency: int = Field(
        default=4, validation_alias="AIGW_PROVIDER_MAX_CONCURRENCY"
    )
    # Per-provider overrides to the global cap. Gemini Code Assist's
    # per-account quota is so tight (~1 concurrent req) that the default of 4
    # still 429s on collection fan-outs — set ``{"gemini": 1}`` here while
    # leaving claude/codex at the global default. The key may be the family
    # name (``gemini``) or the full derived provider string (``gemini-cli``);
    # both match. JSON-parsed from the env var.
    provider_max_concurrency_overrides: dict[str, int] = Field(
        default_factory=dict,
        validation_alias="AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES",
    )

    # Persistent response cache for deterministic chat completions (SF-265, global as of OME-305).
    #
    # WHY the default stays False while the per-call default became opt-OUT: with the flag on, this
    # is one GLOBAL cache shared by every caller of the gateway — a data-sharing posture, not a
    # performance knob. It is turned on deliberately in hosted config
    # (`config.requestCache.enabled` in the chart, on in `values-prod.yaml`), so the decision is
    # visible in the rendered manifest rather than inherited from a code default.
    request_cache_enabled: bool = Field(
        default=False, validation_alias="AIGW_REQUEST_CACHE_ENABLED"
    )
    request_cache_default_ttl_seconds: int = Field(
        default=600, gt=0, validation_alias="AIGW_REQUEST_CACHE_TTL_SECONDS"
    )
    request_cache_max_ttl_seconds: int = Field(
        default=3600, gt=0, validation_alias="AIGW_REQUEST_CACHE_MAX_TTL_SECONDS"
    )
    request_cache_max_response_bytes: int = Field(
        default=1_000_000, gt=0, validation_alias="AIGW_REQUEST_CACHE_MAX_RESPONSE_BYTES"
    )

    # Admin cache-snapshot upload cap (OME-952): the COMPRESSED archive size accepted by
    # POST /v1/admin/cache/snapshots. Deliberately on the compressed bytes — that is what
    # crosses the wire and fills the spool directory — and deliberately generous: the DRACO
    # corpus is ~35 MB gzipped today and snapshots grow with the table.
    cache_upload_max_bytes: int = Field(
        default=268_435_456, gt=0, validation_alias="AIGW_CACHE_UPLOAD_MAX_BYTES"
    )

    # Bounded public-catalog discovery behind /v1/model-parameters (OME-479 §5.2,
    # §5.3). Enabled by default: the evidence it gathers can only RESTRICT what a
    # contract claims, so running without it is the more permissive state, not the
    # safer one. It never touches the chat path, never sees a credential, and
    # degrades to the static observations when a source is unreachable.
    discovery_enabled: bool = Field(default=True, validation_alias="AIGW_DISCOVERY_ENABLED")
    discovery_cache_ttl_seconds: float = Field(
        default=900.0,
        gt=0,
        allow_inf_nan=False,
        validation_alias="AIGW_DISCOVERY_CACHE_TTL_SECONDS",
    )
    # How long a last-good snapshot may still be served, LABELLED STALE, after the
    # TTL expires and the source fails. Zero disables fail-soft entirely.
    discovery_cache_stale_ttl_seconds: float = Field(
        default=3600.0,
        ge=0,
        allow_inf_nan=False,
        validation_alias="AIGW_DISCOVERY_CACHE_STALE_TTL_SECONDS",
    )
    # Suppress repeated sequential dials during a source outage without delaying
    # recovery for more than a small, operator-controlled window.
    discovery_cache_failure_ttl_seconds: float = Field(
        default=5.0,
        ge=0,
        allow_inf_nan=False,
        validation_alias="AIGW_DISCOVERY_CACHE_FAILURE_TTL_SECONDS",
    )
    discovery_cache_max_entries: int = Field(
        default=512, gt=0, validation_alias="AIGW_DISCOVERY_CACHE_MAX_ENTRIES"
    )
    discovery_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        allow_inf_nan=False,
        validation_alias="AIGW_DISCOVERY_TIMEOUT_SECONDS",
    )
    discovery_max_bytes: int = Field(
        default=1_000_000, gt=0, validation_alias="AIGW_DISCOVERY_MAX_BYTES"
    )

    @model_validator(mode="after")
    def _reconcile_auth_mode(self) -> Settings:
        """Derive the mode from the legacy flag, and refuse a configuration that means both.

        An existing deployment sets only ``AIGATEWAY_AUTH_ENABLED``, so that alone must keep
        producing the behavior it always did — ``false`` there means anonymous, i.e. ``disabled``.

        The two settings disagreeing is a hard error rather than a precedence rule: silently
        preferring either one would leave an operator who wrote ``AUTH_ENABLED=false`` alongside
        ``AUTH_MODE=cloudflare_headers`` believing something about their auth posture that is false.
        """
        explicit_mode = "auth_mode" in self.model_fields_set
        if not explicit_mode:
            if not self.auth_enabled:
                self.auth_mode = "disabled"
            return self
        if not self.auth_enabled and self.auth_mode != "disabled":
            raise ValueError(
                "AIGATEWAY_AUTH_ENABLED=false conflicts with "
                f"AIGW_AUTH_MODE={self.auth_mode!r} — drop AIGATEWAY_AUTH_ENABLED and let "
                "AIGW_AUTH_MODE be the only auth setting"
            )
        return self

    @field_validator("allowed_networks", mode="before")
    @classmethod
    def _parse_allowed_networks(cls, value: object) -> object:
        """Parse the comma-separated CIDR list.

        `strict=True` deliberately: it rejects a value with host bits set (`192.168.0.0/8`) instead
        of widening it to the enclosing network (`192.0.0.0/8`), which would silently trust sixteen
        million addresses the operator never named.
        """
        if not isinstance(value, str):
            return value
        return tuple(
            ip_network(entry, strict=True) for part in value.split(",") if (entry := part.strip())
        )

    @field_validator("admin_emails", mode="before")
    @classmethod
    def _parse_admin_emails(cls, value: object) -> object:
        """Parse the comma-separated address list into a case-folded set.

        Lowercased to match `CloudflareIdentity.username`, which lowercases because mail domains
        are case-insensitive. An allowlist stored in a different normal form than the identity it
        is compared against would silently fail to match the first operator who typed a capital.

        Empty entries are dropped rather than kept: a trailing comma would otherwise put `""` in
        the set, which a blank header could match if one ever reached the comparison.
        """
        if not isinstance(value, str):
            return value
        return frozenset(entry.lower() for part in value.split(",") if (entry := part.strip()))

    @model_validator(mode="after")
    def _validate_request_cache_ttls(self) -> Settings:
        if self.request_cache_default_ttl_seconds > self.request_cache_max_ttl_seconds:
            raise ValueError("request cache default TTL must not exceed the max TTL")
        return self

    @field_validator("jwt_secret", "provisioning_token")
    @classmethod
    def _validate_secret_length(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        if len(value.get_secret_value()) < 32:
            raise ValueError("secret must be at least 32 characters")
        return value

    @field_validator("admin_password")
    @classmethod
    def _validate_admin_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        size = len(value.get_secret_value().encode("utf-8"))
        if not 8 <= size <= 72:
            raise ValueError("password must be 8-72 UTF-8 bytes")
        return value

    @field_validator("public_url")
    @classmethod
    def _validate_public_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("public_url must be an absolute http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("public_url must not include query or fragment")
        return normalized

    @field_validator("secret_provider")
    @classmethod
    def _validate_secret_provider(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"local", "kms"}:
            raise ValueError("AIGATEWAY_SECRET_PROVIDER must be 'local' or 'kms'")
        return normalized

    @field_validator("secret_key", mode="before")
    @classmethod
    def _empty_secret_key_is_unset(cls, value: object) -> object:
        """Exactly ``""`` means "no key", because that is what an empty env var means.

        INVARIANT: only the empty string. A blank-but-nonempty value like ``" "`` is a WRONG key,
        not an absent one, and must keep reaching ``secrets.master_key._decode_key`` and crashing
        there at startup. Hence no ``.strip()`` — stripping would silently downgrade a misconfigured
        deployment into the auto-generated-key posture while looking helpful — and no rejecting
        validator, because a raise here would let Pydantic capture the value in
        ``ValidationError(input_value=…)`` and leak it into startup logs (SF-221 review #5).
        """
        return None if value == "" else value
