"""SF Engine provider-connection routes backed by AI Gateway."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr

from screamingface_engine.auth import ProblemException
from screamingface_engine.connections.port import (
    AuthMethod,
    Connection,
    ConnectionError,
    Connections,
    ConnectionStatus,
    OAuthAuthorization,
)
from screamingface_engine.rest.boundary import (
    boundary_route_class,
    declare_x_profile,
    mark_private,
    problem_responses,
)

# `_caller` stays importable from here: the traceparent tests exercise it through this module.
from screamingface_engine.rest.boundary import caller as _caller

logger = logging.getLogger(__name__)


_SecretSafeRoute = boundary_route_class(
    logger=logger,
    log_message="provider connection request validation failed",
    detail="the provider connection request is invalid",
)


router = APIRouter(
    tags=["Connections"],
    route_class=_SecretSafeRoute,
    dependencies=[Depends(declare_x_profile)],
)


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


class OAuthAuthorizationResponse(BaseModel):
    """The public browser authorization fields returned to the Client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["oauth_authorization"] = "oauth_authorization"
    provider: str
    authorize_url: str
    expires_in: int


_ERROR_DESCRIPTIONS = {
    400: (
        "The provider does not support the requested authentication method, or the request "
        "states the unsupported `X-Profile` header (`code: x_profile_unsupported`)."
    ),
    401: "The caller or provider credential was rejected.",
    404: "The provider is not available.",
    409: "The Engine-managed connection state conflicts with this operation.",
    422: "The request body is invalid.",
    429: "Provider connection requests are rate limited.",
    502: "AI Gateway returned an unusable response.",
    503: "Provider connections or AI Gateway are unavailable.",
    504: "AI Gateway did not respond in time.",
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


def _serialize_oauth(authorization: OAuthAuthorization) -> OAuthAuthorizationResponse:
    return OAuthAuthorizationResponse(
        provider=authorization.provider,
        authorize_url=authorization.authorize_url,
        expires_in=authorization.expires_in,
    )


def _service(request: Request) -> Connections:
    service = getattr(request.app.state, "connections", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="provider connections are not configured on this Engine",
        )
    return service


def _problem(exc: ConnectionError) -> ProblemException:
    logger.info("provider connection request failed: %s", type(exc).__name__)
    return ProblemException(status=exc.status, title=exc.title, detail=exc.detail)


@router.get(
    "/v1/connections",
    summary="List provider connections",
    description="Return the safe connection state exposed to the ScreamingFace Client.",
    response_model=ConnectionListResponse,
    responses=problem_responses(_ERROR_DESCRIPTIONS),
)
async def list_connections(request: Request, response: Response) -> ConnectionListResponse:
    try:
        rows = await _service(request).list(_caller(request))
    except ConnectionError as exc:
        raise _problem(exc) from exc
    mark_private(response)
    return ConnectionListResponse(data=tuple(_serialize(row) for row in rows))


@router.put(
    "/v1/connections/{provider}",
    summary="Connect or replace a provider API key",
    response_model=ConnectionResponse,
    responses=problem_responses(_ERROR_DESCRIPTIONS),
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
    mark_private(response)
    return _serialize(connection)


@router.post(
    "/v1/connections/{provider}/oauth",
    status_code=201,
    summary="Start provider OAuth authorization",
    response_model=OAuthAuthorizationResponse,
    responses=problem_responses(_ERROR_DESCRIPTIONS),
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
    mark_private(response)
    return _serialize_oauth(authorization)


@router.delete(
    "/v1/connections/{provider}",
    summary="Disconnect a provider",
    response_model=ConnectionResponse,
    responses=problem_responses(_ERROR_DESCRIPTIONS),
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
    mark_private(response)
    return _serialize(connection)


__all__ = [
    "ConnectionListResponse",
    "ConnectionResponse",
    "OAuthAuthorizationResponse",
    "router",
]
