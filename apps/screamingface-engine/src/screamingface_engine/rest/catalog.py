"""Credential-scoped Engine model discovery.

FEATURE: model-catalog discovery.

STORY: as a client about to compose a url4 expression, I ask screamingface-engine
which models I can address and receive the caller-visible AI Gateway models installed
in this Engine's declared world.

Owns request-side concerns only (credential resolution, conditional-request/ETag handling, mapping
``CatalogError`` to RFC 9457 problems); the actual upstream fetch and per-credential caching live
in ``screamingface_engine.catalog.cache.CatalogService``.

``GET /v1/models`` is the cached summary. ``GET /v1/model-parameters`` is the uncached,
profile-bound detail. Every response is private and varies by the identity inputs that can
change it.

BOTH surfaces are bounded by the same declared execution world
(``screamingface_engine.world.config``):
the summary omits models this Engine has not declared, and the detail refuses them with 404
before any upstream request. Neither reshapes what it does return. When the declared world is
unusable the composition root wires no service at all, and both answer 503.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE, ProblemException
from screamingface_engine.catalog.cache import CatalogService
from screamingface_engine.catalog.port import CatalogError, Credential, ModelParameterSource
from screamingface_engine.rest.conditional import validator_matches
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector

logger = logging.getLogger(__name__)

router = APIRouter()

# INVARIANT: names every header that can change the response body. Without it a shared cache is
# free to serve one caller's catalog to another — the header-level counterpart of keying the cache
# by caller (spec §5.2, §6.3). `X-Profile` stays although it no longer selects anything
# (OME-1381): whether it is present still decides between a catalog and a 400, and a cache that
# served the catalog to a request stating a selector would ignore that selector in silence.
_VARY = "X-Profile, X-User-Email"

# RFC 9110 §11.6.1: a 401 must carry a challenge. `Bearer` with no realm is deliberate — a realm
# would name this deployment's identity provider to an unauthenticated caller. Only used to relay
# an upstream refusal now; this route no longer refuses anyone itself.
_CHALLENGE = {"WWW-Authenticate": "Bearer"}
# The Engine's own refusals are RFC 9457 problems; declared so a generated client can read them.
_PROBLEM_CONTENT = {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}}
_MODEL_PARAMETER_HEADERS = {
    "Cache-Control": "private, no-store",
    "Vary": _VARY,
}
_MODEL_PARAMETER_OPENAPI = {
    "parameters": [
        {
            "name": "model",
            "in": "query",
            "required": True,
            "description": "Canonical provider-prefixed model id.",
            "schema": {"type": "string"},
        }
    ]
}

_MODELS_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"description": "The models this caller can address."},
    304: {"description": "The catalog is unchanged since the supplied `If-None-Match`."},
    400: {
        "description": (
            "The request states the unsupported `X-Profile` header (`code: x_profile_unsupported`)."
        ),
        "content": _PROBLEM_CONTENT,
    },
    401: {"description": "aigateway refused the caller's identity."},
    502: {"description": "aigateway returned an unusable catalog."},
    503: {"description": "The catalog is not configured on this deployment."},
    504: {"description": "aigateway did not respond in time."},
}

_MODEL_PARAMETER_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {"description": "AI Gateway's model-parameter contract."},
    # WHY two media types: the Engine's own refusals (`model` missing, a stated `X-Profile`) are
    # problems, while an invalid canonical model id is AI Gateway's verbatim JSON, relayed as-is.
    400: {
        "description": (
            "The Engine refuses the request (`application/problem+json`): `model` is missing, or "
            "the request states the unsupported `X-Profile` header (`code: x_profile_unsupported`)."
            " Or AI Gateway refuses the canonical model id, relayed verbatim (`application/json`)."
        ),
        "content": {**_PROBLEM_CONTENT, "application/json": {"schema": {}}},
    },
    401: {"description": "The selected profile requires authentication."},
    403: {"description": "The caller cannot access the selected profile."},
    404: {
        "description": (
            "The model is not installed on this Engine, or AI Gateway does not know the "
            "model or profile."
        )
    },
    409: {"description": "The selected profile is not ready."},
    502: {"description": "AI Gateway returned an unusable contract."},
    503: {"description": "AI Gateway is not configured, or the declared world is unusable."},
    504: {"description": "AI Gateway did not respond in time."},
}


@router.get(
    "/v1/models",
    tags=["Catalog"],
    summary="List the models this caller can address",
    responses=_MODELS_RESPONSES,
    description=(
        "List the caller-visible aigateway models installed as routes on this Engine, from a "
        "per-caller cache."
        "\n\n"
        "The caller is the verified ``X-User-Email`` the mesh gateway injects, matching "
        "``GET /?q=``. screamingface-engine verifies nothing and holds no credential of its "
        "own — aigateway "
        "decides, and refuses the request itself when its mode requires an identity that is "
        "absent. Locally, where aigateway runs with auth disabled, no identity is needed.\n\n"
        "Retained model documents are aigateway's verbatim; models outside this Engine's "
        "declared execution world are omitted. Responses are cached per caller, so "
        "``Cache-Control`` is ``private`` and ``ETag``/``If-None-Match`` are scoped to that "
        "caller's catalog."
    ),
)
async def list_models(
    request: Request,
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
    if_none_match: Annotated[
        str | None, Header(alias="If-None-Match", description="Conditional-request validator.")
    ] = None,
) -> Response:
    """List caller-visible AI Gateway models installed in this Engine's execution world.

    The caller is the verified ``X-User-Email`` the mesh gateway injects, matching ``GET /?q=``.
    screamingface-engine verifies nothing and holds no credential of its own — aigateway does.

    Retained documents are passed through unchanged. Responses are cached per caller, so
    ``Cache-Control`` is ``private`` and ``ETag``/``If-None-Match`` are scoped to that caller.
    """
    refuse_selector(request.headers)
    service = _require_service(request)
    credential = _caller(request.headers)
    try:
        catalog = await service.fetch(credential)
    except CatalogError as exc:
        # WHY the exception carries its own status/title/detail: the route needs no isinstance
        # ladder, so a new failure mode never means editing this function. The upstream cause is
        # logged; only the generic detail reaches the caller (spec §5.3).
        logger.info("model catalog request failed: %s", type(exc).__name__)
        raise ProblemException(
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            headers=_CHALLENGE if exc.status == 401 else None,
        ) from exc

    headers = {
        "ETag": f'"{catalog.etag}"',
        "Cache-Control": f"private, max-age={service.max_age_s(credential)}",
        "Vary": _VARY,
    }
    if validator_matches(if_none_match, catalog.etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=catalog.body, headers=headers)


@router.get(
    "/v1/model-parameters",
    tags=["Catalog"],
    summary="Get one model's parameter contract",
    responses=_MODEL_PARAMETER_RESPONSES,
    openapi_extra=_MODEL_PARAMETER_OPENAPI,
    description=(
        "Return AI Gateway's profile-bound parameter contract for one canonical model. "
        "The body is AI Gateway's, verbatim, and is never cached by URL4 Cloud.\n\n"
        "Bounded by the same declared execution world as ``GET /v1/models``: a model this "
        "Engine has not declared answers 404 without contacting AI Gateway, so this surface "
        "and the listing can never describe different execution capabilities."
    ),
)
async def model_parameters(
    request: Request,
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
) -> Response:
    """Return one caller-specific AI Gateway model contract."""

    refuse_selector(request.headers, problem_headers=_MODEL_PARAMETER_HEADERS)
    model = request.query_params.get("model")
    if model is None:
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail="model is required",
            headers=_MODEL_PARAMETER_HEADERS,
        )
    source = _require_model_parameter_source(request)
    try:
        result = await source.fetch_model_parameters(
            _caller(request.headers),
            model,
        )
    except CatalogError as exc:
        logger.info("model-parameter request failed: %s", type(exc).__name__)
        raise ProblemException(
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            headers=_MODEL_PARAMETER_HEADERS,
        ) from exc
    return Response(
        status_code=result.status,
        content=result.content,
        media_type="application/json",
        headers=_model_parameter_headers(result.status),
    )


def _require_service(request: Request) -> CatalogService:
    """The wired catalog service, or a 503.

    WHY this is checked BEFORE the credential: an unconfigured deployment is an operator problem,
    and answering 401 there would send whoever is debugging it hunting for a credential fault that
    does not exist. The deployment's configuration state is not sensitive.
    """
    service = getattr(request.app.state, "catalog", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the model catalog is not configured (URL4_CLOUD_AIGATEWAY_BASE_URL)",
        )
    return service


def _require_model_parameter_source(request: Request) -> ModelParameterSource:
    source = getattr(request.app.state, "model_parameters", None)
    if source is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="model details are not configured (URL4_CLOUD_AIGATEWAY_BASE_URL)",
            headers=_MODEL_PARAMETER_HEADERS,
        )
    return source


def _model_parameter_headers(status: int) -> dict[str, str]:
    """Privacy headers for every result, plus the challenge RFC 9110 requires on 401."""

    if status == 401:
        return {**_MODEL_PARAMETER_HEADERS, **_CHALLENGE}
    return _MODEL_PARAMETER_HEADERS


def _caller(headers: Mapping[str, str]) -> Credential:
    """Resolve who is asking, from the verified identity header the mesh gateway injects.

    WHY there is no 401 here any more: screamingface-engine cannot know which auth
    mode aigateway is in, and an absent identity is legitimate in one of them.
    Deployed, Envoy always injects the header and an aigateway in
    ``cloudflare_headers`` mode 401s a request without it — upstream, where the
    decision belongs. Locally, aigateway runs ``disabled``: every caller is
    anonymous, no identity exists to send, and rejecting here would make the
    endpoint permanently unusable in dev.

    AIDEV-NOTE: this drops the old "an unauthenticated request costs aigateway nothing" short
    circuit (spec §11 acceptance 2), which was only sound while a bearer token was mandatory. The
    flood protection that remains is `catalog.cache`'s entry cap and single-flight bulkhead.

    INVARIANT (OME-1381): selector-less. The route has already refused a stated ``X-Profile``, and
    the absent-profile key is the one a selector-less caller always had, so no cached catalog is
    invalidated by the producer-off change.
    """
    return Credential.derive(None, job_env.identity_from_headers(headers))


__all__ = ["router"]
