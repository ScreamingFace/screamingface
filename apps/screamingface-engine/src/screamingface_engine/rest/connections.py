"""SF Engine provider-connection routes backed by AI Gateway."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, SecretStr

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE, ProblemException
from screamingface_engine.connections.port import (
    AuthMethod,
    Caller,
    Connection,
    ConnectionError,
    Connections,
    ConnectionStatus,
    OAuthAuthorization,
    Provider,
    ProviderCatalog,
    ProviderGroup,
    ProviderKind,
)

logger = logging.getLogger(__name__)


class _SecretSafeRoute(APIRoute):
    """Replace FastAPI's input-bearing validation errors at the credential boundary."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def secret_safe_route_handler(request: Request) -> Response:
            try:
                return await route_handler(request)
            except RequestValidationError:
                logger.info("provider connection request validation failed")
                raise ProblemException(
                    status=422,
                    title="Unprocessable Content",
                    detail="the provider connection request is invalid",
                ) from None

        return secret_safe_route_handler


router = APIRouter(tags=["Connections"], route_class=_SecretSafeRoute)


class ApiKeyRequest(BaseModel):
    """A provider credential accepted only long enough to forward it to AI Gateway."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    api_key: SecretStr


class ConnectionResponse(BaseModel):
    """The complete secret-free connection projection exposed by the Engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["connection"] = "connection"
    provider: str
    display_name: str
    auth_methods: tuple[AuthMethod, ...]
    status: ConnectionStatus
    auth_method: AuthMethod | None = None
    account_label: str | None = None


class ConnectionListResponse(BaseModel):
    """Caller-scoped provider connections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["list"] = "list"
    data: tuple[ConnectionResponse, ...]


class ProviderResponse(BaseModel):
    """Presentation and connection capabilities for one model provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["provider"] = "provider"
    id: str
    display_name: str
    description: str
    kind: ProviderKind
    group: ProviderGroup
    group_display_name: str
    color: str
    sort_order: int
    connection_required: bool
    auth_methods: tuple[AuthMethod, ...]


class ProviderListResponse(BaseModel):
    """The complete provider catalog exposed by this Engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["list"] = "list"
    data: tuple[ProviderResponse, ...]


class OAuthAuthorizationResponse(BaseModel):
    """The public browser authorization fields returned to the Client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["oauth_authorization"] = "oauth_authorization"
    provider: str
    authorize_url: str
    expires_in: int


_ERROR_DESCRIPTIONS = {
    400: "The provider does not support the requested authentication method.",
    401: "The caller or provider credential was rejected.",
    404: "The provider is not available.",
    409: "The Engine-managed connection state conflicts with this operation.",
    422: "The request body is invalid.",
    429: "Provider connection requests are rate limited.",
    502: "AI Gateway returned an unusable response.",
    503: "Provider connections or AI Gateway are unavailable.",
    504: "AI Gateway did not respond in time.",
}


def _error_responses() -> dict[int | str, dict[str, Any]]:
    return {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in _ERROR_DESCRIPTIONS.items()
    }


def _serialize(connection: Connection) -> ConnectionResponse:
    return ConnectionResponse(
        provider=connection.provider,
        display_name=connection.display_name,
        auth_methods=connection.auth_methods,
        status=connection.status,
        auth_method=connection.auth_method,
        account_label=connection.account_label,
    )


def _serialize_provider(provider: Provider) -> ProviderResponse:
    return ProviderResponse(
        id=provider.id,
        display_name=provider.display_name,
        description=provider.description,
        kind=provider.kind,
        group=provider.group,
        group_display_name=provider.group_display_name,
        color=provider.color,
        sort_order=provider.sort_order,
        connection_required=provider.connection_required,
        auth_methods=provider.auth_methods,
    )


def _serialize_oauth(authorization: OAuthAuthorization) -> OAuthAuthorizationResponse:
    return OAuthAuthorizationResponse(
        provider=authorization.provider,
        authorize_url=authorization.authorize_url,
        expires_in=authorization.expires_in,
    )


def _caller(request: Request) -> Caller:
    return Caller(job_env.identity_from_headers(request.headers))


def _service(request: Request) -> Connections:
    service = getattr(request.app.state, "connections", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="provider connections are not configured on this Engine",
        )
    return service


def _provider_service(request: Request) -> ProviderCatalog:
    service = getattr(request.app.state, "provider_catalog", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the provider catalog is not configured on this Engine",
        )
    return service


def _problem(exc: ConnectionError) -> ProblemException:
    logger.info("provider connection request failed: %s", type(exc).__name__)
    return ProblemException(status=exc.status, title=exc.title, detail=exc.detail)


def _mark_private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-User-Email"


@router.get(
    "/v1/providers",
    summary="List model providers",
    description="Return provider-owned metadata and connection capabilities.",
    response_model=ProviderListResponse,
    responses=_error_responses(),
)
async def list_providers(request: Request, response: Response) -> ProviderListResponse:
    try:
        rows = await _provider_service(request).providers(_caller(request))
    except ConnectionError as exc:
        raise _problem(exc) from exc
    _mark_private(response)
    return ProviderListResponse(data=tuple(_serialize_provider(row) for row in rows))


@router.get(
    "/v1/connections",
    summary="List provider connections",
    description="Return the safe connection state exposed to the ScreamingFace Client.",
    response_model=ConnectionListResponse,
    responses=_error_responses(),
)
async def list_connections(request: Request, response: Response) -> ConnectionListResponse:
    try:
        rows = await _service(request).list(_caller(request))
    except ConnectionError as exc:
        raise _problem(exc) from exc
    _mark_private(response)
    return ConnectionListResponse(data=tuple(_serialize(row) for row in rows))


@router.put(
    "/v1/connections/{provider}",
    summary="Connect or replace a provider API key",
    response_model=ConnectionResponse,
    responses=_error_responses(),
)
async def connect_provider(
    request: Request,
    body: ApiKeyRequest,
    response: Response,
    provider: Annotated[str, Path(min_length=1)],
) -> ConnectionResponse:
    try:
        connection = await _service(request).connect(
            _caller(request),
            provider,
            body.api_key.get_secret_value(),
        )
    except ConnectionError as exc:
        raise _problem(exc) from exc
    _mark_private(response)
    return _serialize(connection)


@router.post(
    "/v1/connections/{provider}/oauth",
    status_code=201,
    summary="Start provider OAuth authorization",
    response_model=OAuthAuthorizationResponse,
    responses=_error_responses(),
)
async def start_provider_oauth(
    request: Request,
    response: Response,
    provider: Annotated[str, Path(min_length=1)],
) -> OAuthAuthorizationResponse:
    try:
        authorization = await _service(request).start_oauth(_caller(request), provider)
    except ConnectionError as exc:
        raise _problem(exc) from exc
    _mark_private(response)
    return _serialize_oauth(authorization)


@router.delete(
    "/v1/connections/{provider}",
    summary="Disconnect a provider",
    response_model=ConnectionResponse,
    responses=_error_responses(),
)
async def disconnect_provider(
    request: Request,
    response: Response,
    provider: Annotated[str, Path(min_length=1)],
) -> ConnectionResponse:
    try:
        connection = await _service(request).disconnect(_caller(request), provider)
    except ConnectionError as exc:
        raise _problem(exc) from exc
    _mark_private(response)
    return _serialize(connection)


__all__ = [
    "ConnectionListResponse",
    "ConnectionResponse",
    "OAuthAuthorizationResponse",
    "router",
]
