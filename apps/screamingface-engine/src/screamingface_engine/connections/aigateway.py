"""AI Gateway adapter for the SF Engine provider-connection port."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from screamingface_engine.connections.port import (
    AuthMethod,
    Caller,
    Connection,
    ConnectionAlreadyConnected,
    ConnectionBadResponse,
    ConnectionConflict,
    ConnectionMethodUnsupported,
    ConnectionNotFound,
    ConnectionStatus,
    ConnectionTimeout,
    ConnectionUnavailable,
    OAuthAuthorization,
)
from screamingface_engine.connections.profile_availability import decode_profile_statuses
from screamingface_engine.connections.provider_id import is_provider_id
from screamingface_engine.connections.upstream_errors import raise_for_status

logger = logging.getLogger(__name__)

_PROVIDERS_PATH = "/v1/providers"
_CONNECTIONS_PATH = "/v1/oauth/connections"
_PROFILES_PATH = "/v1/auth/profiles"
_API_KEY_PATH = f"{_CONNECTIONS_PATH}/api-key"
# Inter-service contract: assigning this label explicitly designates a row for ScreamingFace
# management. Rows under every other label remain outside this adapter's public projection.
_MANAGED_LABEL = "screamingface"
_MAX_OAUTH_EXPIRES_IN_SECONDS = 30 * 60
ListingSource = Literal["connections", "profiles"]


@dataclass(frozen=True, slots=True)
class _Provider:
    id: str
    display_name: str
    auth_methods: tuple[AuthMethod, ...]


_UpstreamConnectionStatus = Literal["pending", "active", "expired", "revoked", "error"]


@dataclass(frozen=True, slots=True)
class _ConnectionRow:
    id: UUID
    provider: str
    label: str
    status: _UpstreamConnectionStatus
    auth_type: AuthMethod
    account_label: str | None


class AigatewayConnections:
    """Combine AI Gateway provider capabilities with caller-scoped connection state."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        listing_source: ListingSource = "connections",
    ) -> None:
        self._client = client
        self._listing_source = listing_source

    async def list(self, caller: Caller) -> tuple[Connection, ...]:
        providers = await self._providers(caller)
        if self._listing_source == "profiles":
            statuses = await self._profile_statuses(caller)
            return tuple(
                _profile_connection(provider, statuses.get(provider.id, "not_connected"))
                for provider in providers
            )
        rows = await self._rows(caller)
        return tuple(
            _disconnected(provider)
            if (selected := _select(rows, provider.id)) is None
            else _public(selected, provider)
            for provider in providers
        )

    async def connect(self, caller: Caller, provider: str, api_key: str) -> Connection:
        self._require_mutable()
        selected_provider = _provider(await self._providers(caller), provider)
        if "api_key" not in selected_provider.auth_methods:
            raise ConnectionMethodUnsupported()
        rows = await self._rows(caller, provider=provider)
        selected = _select(rows, provider)
        if selected is None:
            response = await self._request(
                "POST",
                _API_KEY_PATH,
                caller,
                json={"provider": provider, "label": _MANAGED_LABEL, "api_key": api_key},
            )
            expected_status = 201
        else:
            if selected.auth_type != "api_key":
                raise ConnectionAlreadyConnected()
            response = await self._request(
                "PUT",
                f"{_CONNECTIONS_PATH}/{selected.id}/api-key",
                caller,
                json={"api_key": api_key},
            )
            expected_status = 200
        row = _decode_row(response)
        if (
            response.status_code != expected_status
            or row.label != _MANAGED_LABEL
            or row.auth_type != "api_key"
            or row.status != "active"
        ):
            raise ConnectionBadResponse()
        return _public(row, selected_provider)

    async def start_oauth(self, caller: Caller, provider: str) -> OAuthAuthorization:
        self._require_mutable()
        selected_provider = _provider(await self._providers(caller), provider)
        if "oauth" not in selected_provider.auth_methods:
            raise ConnectionMethodUnsupported()
        rows = await self._rows(caller, provider=provider)
        selected = _select(rows, provider)
        if selected is not None:
            raise ConnectionAlreadyConnected()
        response = await self._request(
            "POST",
            _CONNECTIONS_PATH,
            caller,
            json={"provider": provider, "label": _MANAGED_LABEL},
        )
        return _decode_oauth_authorization(response, provider)

    async def disconnect(self, caller: Caller, provider: str) -> Connection:
        self._require_mutable()
        selected_provider = _provider(await self._providers(caller), provider)
        rows = await self._rows(caller, provider=provider)
        selected = _select(rows, provider)
        if selected is None:
            return _disconnected(selected_provider)
        try:
            response = await self._request(
                "DELETE",
                f"{_CONNECTIONS_PATH}/{selected.id}",
                caller,
            )
        except ConnectionNotFound:
            # The caller-visible operation is idempotent. A concurrent disconnect may revoke the
            # row after our list but before our delete; that already achieved the requested state.
            return _disconnected(selected_provider)
        if response.status_code != 204:
            raise ConnectionBadResponse()
        return _disconnected(selected_provider)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _require_mutable(self) -> None:
        # INVARIANT: profile-backed hosted reads and caller-managed OAuth writes use separate
        # Gateway stores. Never accept a credential into state this adapter cannot report or use.
        if self._listing_source == "profiles":
            raise ConnectionMethodUnsupported()

    async def _providers(self, caller: Caller) -> tuple[_Provider, ...]:
        response = await self._request("GET", _PROVIDERS_PATH, caller)
        if response.status_code != 200:
            raise ConnectionBadResponse()
        body = _decode_object(response)
        if body.get("object") != "list" or not isinstance(body.get("data"), list):
            raise ConnectionBadResponse()
        providers = tuple(_validate_provider(row) for row in body["data"])
        ids = tuple(provider.id for provider in providers)
        if len(ids) != len(set(ids)):
            raise ConnectionBadResponse()
        return providers

    async def _rows(
        self,
        caller: Caller,
        *,
        provider: str | None = None,
    ) -> list[_ConnectionRow]:
        response = await self._request(
            "GET",
            _CONNECTIONS_PATH,
            caller,
            params={"provider": provider} if provider is not None else None,
        )
        if response.status_code != 200:
            raise ConnectionBadResponse()
        body = _decode_object(response)
        rows = body.get("connections")
        if not isinstance(rows, list):
            raise ConnectionBadResponse()
        return [_validate_row(row) for row in rows]

    async def _profile_statuses(self, caller: Caller) -> dict[str, ConnectionStatus]:
        response = await self._request("GET", _PROFILES_PATH, caller)
        if response.status_code != 200:
            raise ConnectionBadResponse()
        return decode_profile_statuses(_decode_object(response))

    async def _request(
        self,
        method: str,
        path: str,
        caller: Caller,
        *,
        params: Mapping[str, str] | None = None,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                headers=dict(caller.identity),
                params=params,
                json=json,
            )
        except httpx.TimeoutException as exc:
            logger.warning("AI Gateway provider-connection request timed out")
            raise ConnectionTimeout() from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "AI Gateway provider-connection transport failure (%s)", type(exc).__name__
            )
            raise ConnectionUnavailable() from exc
        raise_for_status(response)
        return response


def _provider(providers: tuple[_Provider, ...], provider: str) -> _Provider:
    selected = next((item for item in providers if item.id == provider), None)
    if selected is None:
        raise ConnectionNotFound()
    return selected


def _select(rows: list[_ConnectionRow], provider: str) -> _ConnectionRow | None:
    managed = [row for row in rows if row.provider == provider and row.label == _MANAGED_LABEL]
    if len(managed) == 1:
        return managed[0]
    if len(managed) > 1:
        raise ConnectionConflict()
    return None


def _disconnected(provider: _Provider) -> Connection:
    return Connection(
        provider=provider.id,
        display_name=provider.display_name,
        auth_methods=provider.auth_methods,
        status="not_connected",
    )


def _profile_connection(
    provider: _Provider,
    status: ConnectionStatus,
) -> Connection:
    return Connection(
        provider=provider.id,
        display_name=provider.display_name,
        auth_methods=provider.auth_methods,
        status=status,
    )


def _public(row: _ConnectionRow, provider: _Provider) -> Connection:
    if row.provider != provider.id:
        raise ConnectionBadResponse()
    status = {
        "active": "connected",
        "pending": "pending",
        "expired": "needs_reauth",
        "revoked": "needs_reauth",
        "error": "error",
    }.get(row.status)
    if status is None:
        raise ConnectionBadResponse()
    auth_method = row.auth_type
    if auth_method not in provider.auth_methods:
        raise ConnectionBadResponse()
    return Connection(
        provider=provider.id,
        display_name=provider.display_name,
        auth_methods=provider.auth_methods,
        status=cast(ConnectionStatus, status),
        auth_method=auth_method,
        account_label=row.account_label if auth_method == "oauth" else None,
    )


def _validate_provider(value: object) -> _Provider:
    if not isinstance(value, dict) or set(value) != {
        "object",
        "id",
        "display_name",
        "auth_methods",
    }:
        raise ConnectionBadResponse()
    methods = value.get("auth_methods")
    if (
        value.get("object") != "provider"
        or not is_provider_id(value.get("id"))
        or not isinstance(value.get("display_name"), str)
        or not value["display_name"].strip()
        or not isinstance(methods, list)
        or not methods
        or any(not isinstance(method, str) for method in methods)
    ):
        raise ConnectionBadResponse()
    if any(method not in {"api_key", "oauth"} for method in methods) or len(methods) != len(
        set(methods)
    ):
        raise ConnectionBadResponse()
    return _Provider(
        id=value["id"],
        display_name=value["display_name"],
        auth_methods=cast(tuple[AuthMethod, ...], tuple(methods)),
    )


def _decode_row(response: httpx.Response) -> _ConnectionRow:
    return _validate_row(_decode_object(response))


def _decode_oauth_authorization(
    response: httpx.Response,
    provider: str,
) -> OAuthAuthorization:
    body = _decode_object(response)
    if response.status_code != 201 or set(body) != {
        "connection_id",
        "authorize_url",
        "state",
        "expires_in",
    }:
        raise ConnectionBadResponse()
    authorize_url = body.get("authorize_url")
    expires_in = body.get("expires_in")
    connection_id = body.get("connection_id")
    state = body.get("state")
    if (
        not _is_uuid(connection_id)
        or not isinstance(state, str)
        or not state.strip()
        or not isinstance(authorize_url, str)
        or not _is_https_url(authorize_url)
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or not 1 <= expires_in <= _MAX_OAUTH_EXPIRES_IN_SECONDS
    ):
        raise ConnectionBadResponse()
    return OAuthAuthorization(provider, authorize_url, expires_in)


def _is_https_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
    )


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _decode_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ConnectionBadResponse() from exc
    if not isinstance(body, dict):
        raise ConnectionBadResponse()
    return body


def _validate_row(value: object) -> _ConnectionRow:
    if not isinstance(value, dict):
        raise ConnectionBadResponse()
    connection_id = value.get("id")
    provider = value.get("provider")
    label = value.get("label")
    status = value.get("status")
    auth_type = value.get("auth_type")
    if (
        not isinstance(connection_id, str)
        or not _is_uuid(connection_id)
        or not is_provider_id(provider)
        or not isinstance(label, str)
        or not label.strip()
        or not isinstance(status, str)
        or status not in {"pending", "active", "expired", "revoked", "error"}
        or not isinstance(auth_type, str)
        or auth_type not in {"api_key", "oauth"}
    ):
        raise ConnectionBadResponse()
    return _ConnectionRow(
        id=UUID(connection_id),
        provider=provider,
        label=label,
        status=cast(_UpstreamConnectionStatus, status),
        auth_type=cast(AuthMethod, auth_type),
        account_label=_account_label(value.get("account")),
    )


def _account_label(value: object) -> str | None:
    """Extract AI Gateway's safe display label without retaining raw account metadata."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConnectionBadResponse()
    for field in ("email", "name", "sub"):
        candidate = value.get(field)
        if candidate is None:
            continue
        if not isinstance(candidate, str) or not candidate.strip():
            raise ConnectionBadResponse()
        return candidate.strip()
    return None


__all__ = ["AigatewayConnections", "ListingSource"]
