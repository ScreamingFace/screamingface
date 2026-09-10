"""AI Gateway adapter for model-list and profile-bound model-detail discovery.

Implements both discovery ports in ``catalog/port.py`` with one HTTP client and one identity
boundary. The model list is cached by its decorator; detailed parameter contracts deliberately
pass through uncached.
"""

from __future__ import annotations

import logging
from typing import Any, Never

import httpx

from screamingface_engine.catalog.admission import AdmissionAnswer
from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogRejected,
    CatalogUnavailable,
    Credential,
    ModelCatalog,
    ModelParameterBadResponse,
    ModelParameterResponse,
    compute_etag,
)

logger = logging.getLogger(__name__)

_CATALOG_PATH = "/v1/models"
_MODEL_PARAMETERS_PATH = "/v1/model-parameters"
_ADMIT_PATH = "/v1/models/admit"
# WHY: these statuses describe caller-correctable identity, profile, or model choices. Preserve
# their JSON verbatim; mask every server/transport failure behind the Engine's stable 502/504.
_CALLER_CORRECTABLE_STATUSES = frozenset({400, 401, 403, 404, 409})

# WHY: aigateway may refuse a credential with either 401 or 403; both are treated as
# a bad credential (CatalogRejected, always surfaced as 401) rather than CatalogBadResponse.
_REJECTION_STATUSES = frozenset({401, 403})

# INVARIANT: two attempts total — one retry after a timeout, never a loop — so a genuinely
# down gateway still fails within a bounded wall time (see `_request`, OME-1170).
_TIMEOUT_ATTEMPTS = 2


class AigatewayCatalogSource:
    """Fetch and minimally validate AI Gateway model discovery for one caller."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, credential: Credential) -> ModelCatalog:
        """Fetch the catalog for ``credential``, raising a typed ``CatalogError`` on failure.

        401/403 map to ``CatalogRejected``; other >=300 statuses, non-JSON bodies,
        and malformed payloads map to ``CatalogBadResponse``; a timeout maps to
        ``CatalogUnavailable``.
        """
        response = await self._request(
            _CATALOG_PATH,
            credential,
            label="catalog",
            bad_response=CatalogBadResponse,
        )
        if response.status_code in _REJECTION_STATUSES:
            logger.info("aigateway refused the catalog request (status=%d)", response.status_code)
            raise CatalogRejected(CatalogRejected.detail)
        if response.status_code >= 300:
            logger.warning("aigateway catalog returned status=%d", response.status_code)
            raise CatalogBadResponse(CatalogBadResponse.detail)
        body = self._decode_object(response)
        _validate(body)
        return ModelCatalog(body=body, etag=compute_etag(body))

    async def fetch_model_parameters(
        self,
        credential: Credential,
        model: str,
    ) -> ModelParameterResponse:
        """Fetch one detailed model contract for the caller's profile."""

        response = await self._request(
            _MODEL_PARAMETERS_PATH,
            credential,
            params={"model": model},
            label="model-parameter",
            bad_response=ModelParameterBadResponse,
        )
        body = self._decode_json(
            response,
            bad_response=ModelParameterBadResponse,
            label="model-parameter",
        )
        if response.status_code in _CALLER_CORRECTABLE_STATUSES:
            return ModelParameterResponse(status=response.status_code, content=response.content)
        if response.status_code >= 300:
            raise ModelParameterBadResponse(ModelParameterBadResponse.detail)
        _validate_model_parameters(body, model)
        return ModelParameterResponse(status=response.status_code, content=response.content)

    async def admit_model(self, credential: Credential, model: str) -> AdmissionAnswer:
        """Ask the gateway to dynamically admit ``model`` for this caller (OME-880).

        Total by design — it never raises. Anything short of a well-formed
        admit/refuse answer (endpoint missing on an older gateway, transport
        failure, unreadable body, non-200 status) collapses to ``unsupported``,
        which the caller treats exactly like today's not-installed refusal.
        """
        body: object = None
        try:
            response = await self._client.post(
                _ADMIT_PATH, json={"model_id": model}, headers=_headers(credential)
            )
            if response.status_code == 200:
                body = response.json(parse_constant=_reject_non_json_constant)
            else:
                logger.info("aigateway admit endpoint answered status=%d", response.status_code)
        except httpx.HTTPError:
            logger.warning("aigateway admit request failed at the transport layer")
        except ValueError:
            logger.warning("aigateway admit response was not JSON")
        return _decode_admission(body)

    async def _request(
        self,
        path: str,
        credential: Credential,
        *,
        label: str,
        bad_response: type[CatalogBadResponse],
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue one upstream GET and translate transport failures at the adapter boundary.

        WHY one retry on timeout only (OME-1170): a cold gateway composes a parameter
        datasheet slowly, and that failed slow attempt fills the gateway's cache — so an
        immediate second attempt answers in milliseconds. Other transport failures (refused
        connection, reset) gain nothing from an instant repeat, so they are not retried.
        The retry is bounded: two attempts total, then ``CatalogUnavailable``.
        """

        for attempt in range(_TIMEOUT_ATTEMPTS):
            try:
                return await self._client.get(path, params=params, headers=_headers(credential))
            except httpx.TimeoutException as exc:
                if attempt + 1 < _TIMEOUT_ATTEMPTS:
                    logger.warning("aigateway %s request timed out; retrying once", label)
                    continue
                logger.warning("aigateway %s request timed out", label)
                raise CatalogUnavailable(CatalogUnavailable.detail) from exc
            except httpx.HTTPError as exc:
                logger.warning("aigateway %s request failed at the transport layer", label)
                raise bad_response(bad_response.detail) from exc
        raise AssertionError("unreachable: the final attempt returns or raises")

    def _decode_json(
        self,
        response: httpx.Response,
        *,
        bad_response: type[CatalogBadResponse] = CatalogBadResponse,
        label: str = "catalog",
    ) -> Any:
        """Validate one upstream body as JSON without changing the bytes returned downstream."""

        # INVARIANT: decoding is inspection only. The proxy returns ``response.content`` so
        # unknown fields and valid numbers outside Python's finite float range survive unchanged.
        try:
            return response.json(parse_constant=_reject_non_json_constant)
        except ValueError as exc:
            logger.warning("aigateway %s response was not JSON", label)
            raise bad_response(bad_response.detail) from exc

    def _decode_object(
        self,
        response: httpx.Response,
        *,
        bad_response: type[CatalogBadResponse] = CatalogBadResponse,
        label: str = "catalog",
    ) -> dict[str, Any]:
        """Parse one upstream response as a JSON object, or raise its typed failure."""

        body = self._decode_json(response, bad_response=bad_response, label=label)
        if not isinstance(body, dict):
            raise bad_response(bad_response.detail)
        return body


def _decode_admission(body: object) -> AdmissionAnswer:
    """Read one admit-endpoint body into an answer. Anything unreadable is ``unsupported``."""
    if not isinstance(body, dict) or not isinstance(body.get("admitted"), bool):
        return AdmissionAnswer(outcome="unsupported")
    if body["admitted"]:
        return AdmissionAnswer(outcome="admitted")
    code = body.get("code")
    message = body.get("message")
    return AdmissionAnswer(
        outcome="refused",
        code=code if isinstance(code, str) else None,
        message=message if isinstance(message, str) else None,
    )


def _reject_non_json_constant(value: str) -> Never:
    """Reject JavaScript constants that Python's permissive decoder otherwise accepts."""

    raise ValueError(f"{value} is not valid JSON")


def _headers(credential: Credential) -> dict[str, str]:
    """Build the upstream request headers from the credential's identity and profile.

    INVARIANT: the gateway-owned header is written LAST, mirroring ``runner.connector._headers`` —
    the identity mapping is not guaranteed to hold only identity keys, so no value in it can
    displace ``X-Profile``.

    No ``Authorization``: a deployed aigateway (``cloudflare_headers``) reads only the identity
    header, and a local one (``disabled``) reads nothing at all.

    AIDEV-NOTE (OME-1119): this function carries NO ``traceparent``, and the three callers do not
    all want that for the same reason — so do not "fix" it in one place.

    - ``fetch`` genuinely must not carry one. ``CachedCatalog`` coalesces concurrent misses for a
      credential onto a single upstream fetch (``cache.py``'s ``_inflight``, typed
      ``Future[ModelCatalog]``) and serves the result to every waiter, so that call is *caused by*
      whichever caller led the refresh and *consumed by* N others. Stamping the leader's trace
      would put a call in their trace that also served people they never heard of, and leave the
      other N-1 with a gap where a catalog read should be — both readings wrong, and the wrong one
      looks right. Representing it honestly needs an OTel span Link (one span, many causes), which
      is Phase 2, ``OME-1130``.
    - ``fetch_model_parameters`` and ``admit_model`` are NOT coalesced — ``_inflight`` covers only
      ``fetch``, and ``CachedCatalog.model_parameter_source`` is documented as "the uncached detail
      source". ``rest/catalog.py`` calls the first straight from a route, one upstream call per
      inbound request. Those two SHOULD carry the caller's traceparent; they do not yet, because
      the value has to be threaded from the REST edge through ``catalog/executable.py`` rather than
      taken from ``Credential`` — ``Credential`` holds a derived cache ``key``, so a per-request
      field on it would give every request its own cache entry and destroy the catalog cache.
      Tracked as ``OME-1134``.
    """
    headers = dict(credential.identity)
    if credential.profile is not None:
        headers["X-Profile"] = credential.profile
    return headers


def _validate(body: dict[str, Any]) -> None:
    """Raise ``CatalogBadResponse`` unless ``body`` is a well-formed OpenAI-style model list."""
    if body.get("object") != "list":
        raise CatalogBadResponse(CatalogBadResponse.detail)
    data = body.get("data")
    if not isinstance(data, list):
        raise CatalogBadResponse(CatalogBadResponse.detail)
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise CatalogBadResponse(CatalogBadResponse.detail)


def _validate_model_parameters(body: object, model: str) -> None:
    """Reject a success document that cannot describe the requested model."""

    # INVARIANT: success must identify the exact requested model and contain every envelope the
    # Client needs to preflight; unknown fields remain owned by AI Gateway and pass through.
    selected = body.get("model") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or isinstance(body.get("schema_version"), bool)
        or not isinstance(body.get("schema_version"), int)
        or not isinstance(selected, dict)
        or selected.get("id") != model
        or not isinstance(body.get("parameters"), dict)
        or not isinstance(body.get("tools"), dict)
        or not isinstance(body.get("transport"), dict)
    ):
        raise ModelParameterBadResponse(ModelParameterBadResponse.detail)


__all__ = ["AigatewayCatalogSource"]
