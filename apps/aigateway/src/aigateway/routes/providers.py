"""Credential-provider discovery derived from the loaded plugin registry."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..core.auth.middleware import CurrentAccount
from ..core.endpoint_access import EndpointOperation, permits

router = APIRouter()

# WHY private: a configured endpoint is listed only to the accounts granted it, so the rows
# differ per caller and no shared cache may keep them.
_PRIVATE_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "private, no-store",
    "Vary": "Authorization",
}


@router.get("/v1/providers")
async def list_providers(
    request: Request, response: Response, current: CurrentAccount
) -> dict[str, object]:
    """List enabled model providers whose credentials a caller can manage."""

    response.headers.update(_PRIVATE_CACHE_HEADERS)
    rows: list[dict[str, object]] = []
    for plugin in request.app.state.providers.all():
        provider = plugin.custom_llm_provider
        if not permits(
            request.app, provider, account_id=str(current.id), operation=EndpointOperation.VIEW
        ):
            continue
        auth_methods = tuple(method for method in plugin.available_auth_modes() if method != "none")
        if not auth_methods or not plugin.register_models():
            continue
        rows.append(
            {
                "object": "provider",
                "id": provider,
                "display_name": plugin.provider_display_name,
                "auth_methods": list(auth_methods),
            }
        )
    rows.sort(key=lambda row: str(row["id"]))
    return {"object": "list", "data": rows}


__all__ = ["router"]
