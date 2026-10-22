from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import SecretStr

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationState,
    api_key_validation_message,
)
from aigateway.core.auth.middleware import CurrentAccount
from aigateway.core.endpoint_access import EndpointOperation, accessible_plugin
from aigateway.core.oauth.schemas import ApiKeyValidationResponse, ValidateApiKeyRequest

router = APIRouter()

_MUTATION_ERRORS = {
    ApiKeyValidationState.INVALID: (422, "api_key_invalid"),
    ApiKeyValidationState.EXPIRED: (422, "api_key_expired"),
    ApiKeyValidationState.NO_QUOTA: (402, "api_key_no_quota"),
    ApiKeyValidationState.PERMISSION_DENIED: (403, "api_key_permission_denied"),
    ApiKeyValidationState.RATE_LIMITED: (429, "api_key_validation_rate_limited"),
    ApiKeyValidationState.UNAVAILABLE: (503, "api_key_validation_unavailable"),
    ApiKeyValidationState.MISCONFIGURED: (503, "api_key_validation_misconfigured"),
}


def normalize_api_key(raw_key: SecretStr) -> str:
    api_key = raw_key.get_secret_value().strip()
    if len(api_key) < 8:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_api_key", "message": "api_key is missing or too short"},
        )
    return api_key


def api_key_validation_response(
    provider: str,
    result: ApiKeyValidationResult,
) -> ApiKeyValidationResponse:
    return ApiKeyValidationResponse(
        provider=provider,
        state=result.state,
        message=api_key_validation_message(result.state),
        retryable=result.retryable,
        stage=result.stage,
        retry_after_seconds=result.retry_after_seconds,
        probe_model=result.probe_model,
    )


def _unsupported(provider: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "api_key_not_supported", "provider": provider},
    )


async def run_api_key_validation(
    request: Request,
    plugin,
    provider: str,
    api_key: str,
) -> ApiKeyValidationResult:
    result = await request.app.state.api_key_validation_service.validate(
        plugin,
        provider,
        api_key,
    )
    if result is None:
        raise _unsupported(provider)
    return result


async def require_valid_api_key(
    request: Request,
    plugin,
    provider: str,
    api_key: str,
) -> None:
    result = await run_api_key_validation(request, plugin, provider, api_key)
    if result.state is ApiKeyValidationState.VALID:
        return
    status_code, code = _MUTATION_ERRORS[result.state]
    detail = {
        "code": code,
        "provider": provider,
        "state": result.state,
        "message": api_key_validation_message(result.state),
        "retryable": result.retryable,
        "stage": result.stage,
        "retry_after_seconds": result.retry_after_seconds,
        "probe_model": result.probe_model,
    }
    headers = None
    if result.retry_after_seconds is not None and result.retry_after_seconds > 0:
        headers = {"Retry-After": str(result.retry_after_seconds)}
    raise HTTPException(status_code=status_code, detail=detail, headers=headers)


@router.post(
    "/v1/oauth/connections/api-key/validate",
    response_model=ApiKeyValidationResponse,
)
async def validate_api_key(
    body: ValidateApiKeyRequest,
    request: Request,
    current: CurrentAccount,
) -> ApiKeyValidationResponse:
    """Validate authentication and readiness; the minimal inference may consume quota or credit."""
    plugin = accessible_plugin(
        request.app, body.provider, account_id=str(current.id), operation=EndpointOperation.VALIDATE
    )
    if plugin is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_provider", "provider": body.provider},
        )
    api_key = normalize_api_key(body.api_key)
    result = await run_api_key_validation(request, plugin, body.provider, api_key)
    return api_key_validation_response(body.provider, result)
