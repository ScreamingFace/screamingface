"""GET /v1/classifiers and GET /v1/classifiers/details — the caller's classifier catalog.

# FEATURE: hosted BYOM Unit 3 — an account lists the classifiers granted to it and reads, for one,
# the task it is asked, the contract it answers in and whether its own Connection can run it.
# INVARIANT (spec G5): the VIEW grant gates both routes, and every answer, success or refusal, is
# `private, no-store` and varies by authorization, as for `/v1/model-parameters`.
# INVARIANT: the grant precedes the alias lookup, so an ungranted caller cannot probe aliases.
# INVARIANT: no answer names an origin or a request path, and nothing here reaches the upstream.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..core.auth.middleware import CurrentAccount
from ..core.endpoint_access import EndpointOperation, accessible_plugin, permits
from ..core.plugin_base import CLASSIFICATION_RESULT_CONTRACT, ClassifierEntry
from ..core.provider_access import ResolvePolicy, provider_access_for
from .model_parameters import execution_access
from .provider_access_http import refusals_as_http, selector_from_request

router = APIRouter()

# WHY private: the rows and the access status differ per caller, so no shared cache may keep them.
_PRIVATE_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "private, no-store",
    "Vary": "Authorization",
}


def _row(provider: str, entry: ClassifierEntry) -> dict[str, Any]:
    return {
        "object": "classifier",
        "id": entry.model_name,
        "owned_by": provider,
        "task": entry.task,
        "contract": entry.contract,
    }


@router.get("/v1/classifiers")
async def list_classifiers(
    request: Request, response: Response, current: CurrentAccount
) -> dict[str, Any]:
    account_id = str(current.id)
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    data = [
        _row(plugin.custom_llm_provider, entry)
        for plugin in request.app.state.providers.all()
        if permits(
            request.app,
            plugin.custom_llm_provider,
            account_id=account_id,
            operation=EndpointOperation.VIEW,
        )
        for entry in plugin.register_classifiers()
    ]
    return {"object": "list", "data": data}


@router.get("/v1/classifiers/details")
async def classifier_details(
    request: Request,
    response: Response,
    current: CurrentAccount,
    model: Annotated[str, Query()],
) -> dict[str, Any]:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    try:
        return await _details(request, account_id=str(current.id), model=model)
    except HTTPException as exc:
        # WHY: a raised refusal is rendered from its own headers only, so the policy goes there
        # too, last, as `/v1/model-parameters` does.
        exc.headers = {**(exc.headers or {}), **_PRIVATE_CACHE_HEADERS}
        raise


async def _details(request: Request, *, account_id: str, model: str) -> dict[str, Any]:
    with refusals_as_http():
        selector = selector_from_request(request)
    provider = model.split("/", 1)[0] if "/" in model else None
    if not provider:
        raise HTTPException(status_code=400, detail="model must be provider-prefixed")

    plugin = accessible_plugin(
        request.app, provider, account_id=account_id, operation=EndpointOperation.VIEW
    )
    if plugin is None:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    entry = next((e for e in plugin.register_classifiers() if e.model_name == model), None)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "provider": provider, "model": model},
        )

    # INVARIANT: the datasheet resolve of `/v1/model-parameters`; it reads whether a key is
    # attached and never the key itself.
    access = provider_access_for(request.app)
    with refusals_as_http():
        target = await access.resolve(
            account_id, provider, selector, plugin=plugin, policy=ResolvePolicy.DATASHEET
        )
    return {
        **_row(provider, entry),
        "result_contract": CLASSIFICATION_RESULT_CONTRACT,
        "execution_access": execution_access(target, plugin),
    }
