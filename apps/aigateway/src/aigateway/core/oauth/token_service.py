from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from aigateway.core.errors import AuthError, CredentialNotFoundError, ReauthRequiredError
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access.connection_locator import credential_name_from_locator


class OAuthConnectionStoreLike(Protocol):
    async def get(self, account_id: str | UUID, connection_id: UUID) -> Any | None: ...

    async def mark_error(self, connection: Any, message: str) -> Any: ...

    async def touch_last_refreshed(self, connection: Any) -> Any: ...

    async def touch_last_used(self, connection: Any) -> Any: ...


class ProviderRegistryLike(Protocol):
    def get(self, provider: str) -> Any | None: ...


class TokenWithExpiryStrategy(Protocol):
    async def get_token_with_expiry(self) -> tuple[str, int, bool]: ...


class StrategyCacheLike(Protocol):
    def get_or_create(
        self,
        *,
        provider: str,
        auth_type: str,
        credential_name: str,
        build: Callable[[], Any],
    ) -> Any: ...


@dataclass(frozen=True)
class OAuthConnectionToken:
    connection: OAuthConnection
    access_token: str
    expires_at_ms: int
    refreshed: bool


class OAuthConnectionTokenError(Exception):
    def __init__(self, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class OAuthConnectionTokenService:
    """Mint a fresh access token for an OAuth connection.

    Stateless use-case orchestrator: it resolves the connection, then defers to
    the SHARED ``CredentialStrategyCache`` strategy whose ``asyncio.Lock``
    single-flights the OAuth refresh across the token endpoint, chat dispatch,
    and manual refresh (SF-323). It holds no lock of its own — the strategy is
    the one and only refresh single-flight point (SF-282).
    """

    async def get_token(
        self,
        *,
        account_id: str | UUID,
        connection_id: UUID,
        store: OAuthConnectionStoreLike,
        providers: ProviderRegistryLike,
        credential_store: Any,
        http_client_factory_for,
        strategy_cache: StrategyCacheLike,
    ) -> OAuthConnectionToken:
        connection = await store.get(account_id, connection_id)
        if connection is None:
            raise OAuthConnectionTokenError(404, {"code": "connection_not_found"})
        if connection.status != "active":
            raise OAuthConnectionTokenError(409, {"code": "connection_not_active"})
        if getattr(connection, "auth_type", "oauth") == "api_key":
            # An api-key connection has no OAuth access token to mint; the
            # OAuth strategy cannot parse its blob. Reject explicitly instead
            # of surfacing the misleading "provider_does_not_use_oauth".
            raise OAuthConnectionTokenError(400, {"code": "connection_not_oauth"})

        plugin = providers.get(connection.provider)
        if plugin is None:
            raise OAuthConnectionTokenError(404, {"code": "unknown_provider"})
        # Resolve the SHARED strategy (keyed identically to routes/chat.py) so its
        # asyncio.Lock single-flights the refresh across the token endpoint, chat
        # dispatch, and manual refresh (SF-323). Building is only a constructor
        # call; the cache is evicted on every credential mutation.
        # WHY the locator (S2'b4): a migrated pair's effective row addresses the Profile blob;
        # a plain row's UUID locator (or a duck-typed row without one) derives today's UUID name.
        credential_name = credential_name_from_locator(
            getattr(connection, "credential_locator", None),
            credential_provider=credential_service_provider_for(plugin, connection.provider),
            account_id=str(account_id),
            connection_id=connection.id,
        )
        strategy = strategy_cache.get_or_create(
            provider=connection.provider,
            auth_type="oauth",
            credential_name=credential_name,
            build=lambda: plugin.oauth_strategy_for(
                credential_name,
                credential_store=credential_store,
                http_client_factory=http_client_factory_for(connection.provider),
            ),
        )
        if strategy is None:
            raise OAuthConnectionTokenError(400, {"code": "provider_does_not_use_oauth"})
        token_strategy = cast(TokenWithExpiryStrategy, strategy)

        try:
            access_token, expires_at_ms, refreshed = await token_strategy.get_token_with_expiry()
        except (CredentialNotFoundError, ReauthRequiredError) as exc:
            # Credential missing, or the refresh token was rejected by the provider
            # (revoked / invalid_grant). The connection cannot recover without a new
            # browser auth, so mark it errored and tell the caller to re-auth.
            await store.mark_error(connection, str(exc))
            raise OAuthConnectionTokenError(
                401, {"code": "auth_required", "message": str(exc)}
            ) from exc
        except AuthError as exc:
            # Transient upstream refresh failure (network error, provider 5xx). Leave
            # the connection active and surface 503 so callers back off and retry.
            raise OAuthConnectionTokenError(
                503, {"code": "upstream_refresh_failed", "message": str(exc)}
            ) from exc

        if refreshed:
            await store.touch_last_refreshed(connection)
        await store.touch_last_used(connection)
        return OAuthConnectionToken(
            connection=connection,
            access_token=access_token,
            expires_at_ms=expires_at_ms,
            refreshed=refreshed,
        )


def oauth_connection_token_service(app: Any) -> OAuthConnectionTokenService:
    state = getattr(app, "state", None)
    if state is None:
        raise RuntimeError("AIGateway app state is unavailable")
    service = getattr(state, "oauth_connection_token_service", None)
    if not isinstance(service, OAuthConnectionTokenService):
        service = OAuthConnectionTokenService()
        state.oauth_connection_token_service = service
    return service
