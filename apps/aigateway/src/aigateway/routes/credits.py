"""Caller-owned credit observations and write-only management-key setup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID, CurrentAccount
from aigateway.core.credits import CreditStatus
from aigateway.core.credits.service import (
    CreditService,
    CreditStoreUnavailable,
    ManagementKeyRejected,
)
from aigateway.core.endpoint_access import EndpointOperation, accessible_plugin
from aigateway.core.provider_access import (
    ProviderAccessRefusal,
    SelectorUnsupported,
    provider_access_for,
)
from aigateway.routes.provider_access_http import selector_from_request


class _SafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request: Request) -> Response:
            try:
                selector_from_request(request)
                return await handler(request)
            except SelectorUnsupported:
                raise HTTPException(400, "X-Profile is no longer supported") from None
            except RequestValidationError:
                raise HTTPException(422, "Invalid credit request") from None
            except CreditStoreUnavailable:
                raise HTTPException(503, "Credit settings are unavailable") from None

        return safe


router = APIRouter(route_class=_SafeRoute)


class ManagementKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    api_key: SecretStr = Field(min_length=1, max_length=4096)


def _service(request: Request) -> CreditService:
    return request.app.state.credits


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-User-Email"


async def _inference_key(
    request: Request, account: str, provider: str, *, stored_only: bool = False
) -> str | None:
    plugin = accessible_plugin(
        request.app, provider, account_id=account, operation=EndpointOperation.VIEW
    )
    if plugin is None:
        raise HTTPException(404, "Provider unavailable")
    if not _service(request).supports(provider):
        return None
    access = provider_access_for(request.app)
    try:
        target = await access.resolve(
            account, provider, selector_from_request(request), plugin=plugin
        )
        if stored_only and (target.kind != "stored" or target.auth_type != "api_key"):
            return None
        authorization = await access.authorize(target, plugin=plugin, provider=provider)
    except ProviderAccessRefusal:
        # INVARIANT: provider-authored refusal text never becomes a credit error message.
        return None
    header = next((v for k, v in authorization.headers.items() if k.lower() == "authorization"), "")
    return header[7:] if header.startswith("Bearer ") and len(header) > 7 else None


@router.get("/v1/credits/{provider}", response_model=CreditStatus)
async def read_credits(
    request: Request,
    response: Response,
    current: CurrentAccount,
    provider: str,
    refresh: bool = True,
) -> CreditStatus:
    account = str(current.id)
    key = await _inference_key(request, account, provider)
    result = await _service(request).read(account, provider, key, refresh=refresh)
    if key != await _inference_key(request, account, provider):
        raise HTTPException(409, "Provider connection changed during credit lookup")
    _private(response)
    return result


@router.put("/v1/credits/{provider}/management-key", status_code=204)
async def configure_management_key(
    request: Request,
    current: CurrentAccount,
    provider: str,
    body: ManagementKeyRequest,
) -> Response:
    account = str(current.id)
    key = await _inference_key(request, account, provider)
    secret = body.api_key.get_secret_value().strip()
    if not secret or any(char.isspace() for char in secret):
        raise HTTPException(422, "Invalid credit request")
    if key is None:
        raise HTTPException(409, "A supported provider connection is required")
    try:
        await _service(request).configure(account, provider, key, secret)
    except ManagementKeyRejected:
        raise HTTPException(
            409, "Account balance could not be verified for this connection"
        ) from None
    response = Response(status_code=204)
    _private(response)
    return response


@router.delete("/v1/credits/{provider}/management-key", status_code=204)
async def remove_management_key(
    request: Request, current: CurrentAccount, provider: str
) -> Response:
    # WHY: cleanup stays possible after the inference key is removed or access is revoked.
    await _service(request).remove(str(current.id), provider)
    response = Response(status_code=204)
    _private(response)
    return response


@router.get("/v1/credits/{provider}/key", response_model=CreditStatus)
async def read_key_allowance(
    request: Request,
    response: Response,
    current: CurrentAccount,
    provider: str,
    refresh: bool = True,
) -> CreditStatus:
    # Hosted users have limited keys on their own execution connections, never an
    # anonymous/shared credential fallback. No management credential is read on this path.
    account = str(current.id)
    if account == str(ANONYMOUS_ACCOUNT_ID):
        raise HTTPException(401, "A caller identity is required for key allowance")
    key = await _inference_key(request, account, provider, stored_only=True)
    result = await _service(request).read(
        account,
        provider,
        key,
        refresh=refresh,
        include_account=False,
    )
    if key != await _inference_key(request, account, provider, stored_only=True):
        raise HTTPException(409, "Provider connection changed during credit lookup")
    _private(response)
    return result
