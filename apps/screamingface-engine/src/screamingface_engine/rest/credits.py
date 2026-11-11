"""Credit visibility follows the connection adapter's local/hosted policy."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from screamingface_engine.auth import ProblemException
from screamingface_engine.connections.credits import CreditStatus, GatewayCredits
from screamingface_engine.connections.port import ConnectionError
from screamingface_engine.rest.connections import (
    _declare_x_profile,
    _mark_private,
    _SecretSafeRoute,
)
from screamingface_engine.rest.gateway_route import caller_from_request

router = APIRouter(
    tags=["Credits"], route_class=_SecretSafeRoute, dependencies=[Depends(_declare_x_profile)]
)
Provider = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=100)]


class ManagementKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    api_key: SecretStr = Field(min_length=1, max_length=4096)


def _service(request: Request) -> GatewayCredits:
    service = getattr(getattr(request.app.state, "connections", None), "credits", None)
    if service is None:
        raise ProblemException(
            status=503, title="Service Unavailable", detail="credit lookup is unavailable"
        )
    return cast(GatewayCredits, service)


@router.get("/v1/credits/{provider}", response_model=CreditStatus)
async def read_credits(
    request: Request, response: Response, provider: Provider, refresh: bool = True
) -> CreditStatus:
    try:
        result = await _service(request).read(
            caller_from_request(request), provider, refresh=refresh
        )
    except ConnectionError as exc:
        raise ProblemException(
            status=exc.status, title=exc.title, detail="Credit request could not be completed"
        ) from None
    _mark_private(response)
    return result


@router.put("/v1/credits/{provider}/management-key", status_code=204)
async def configure_management_key(
    request: Request, provider: Provider, body: ManagementKeyRequest
) -> Response:
    try:
        await _service(request).configure(
            caller_from_request(request), provider, body.api_key.get_secret_value()
        )
    except ConnectionError as exc:
        raise ProblemException(
            status=exc.status, title=exc.title, detail="Credit request could not be completed"
        ) from None
    response = Response(status_code=204)
    _mark_private(response)
    return response


@router.delete("/v1/credits/{provider}/management-key", status_code=204)
async def remove_management_key(request: Request, provider: Provider) -> Response:
    try:
        await _service(request).remove(caller_from_request(request), provider)
    except ConnectionError as exc:
        raise ProblemException(
            status=exc.status, title=exc.title, detail="Credit request could not be completed"
        ) from None
    response = Response(status_code=204)
    _mark_private(response)
    return response
