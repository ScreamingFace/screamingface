"""Project AI Gateway discovery onto the Engine's declared execution world."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Protocol

from screamingface_engine.catalog.admission import (
    AdmittedModels,
    ModelAdmissionSource,
    is_dynamically_admissible,
)
from screamingface_engine.catalog.cache import CacheCounters, CatalogService
from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    Credential,
    ModelCatalog,
    ModelNotInstalled,
    ModelParameterResponse,
    ModelParameterSource,
    compute_etag,
)
from screamingface_engine.world.models.registry import decode_route_id, encode_route_id


class ExecutableCatalogSource(CatalogService, Protocol):
    """The managed catalog surface preserved by the executable-world decorator."""

    @property
    def counters(self) -> CacheCounters | None: ...

    @property
    def entry_count(self) -> int: ...

    @property
    def model_parameter_source(self) -> ModelParameterSource | None: ...

    async def aclose(self) -> None: ...


class ExecutableCatalog:
    """A catalog decorator that keeps only model documents installed on this Engine.

    The wrapped cache remains caller-scoped and stores AI Gateway's authoritative response.
    Projection happens after that fetch so one deployment-level route set cannot leak into the
    Gateway adapter's provider/profile contract. Retained model documents and unknown top-level
    fields pass through unchanged.

    OME-880: beside the frozen declared set there is a mutable ``AdmittedModels`` overlay —
    ids the gateway dynamically admitted this deployment. Overlay members survive the
    projection exactly like declared ids; the overlay is fed by the model-parameter source
    below, never here.
    """

    def __init__(
        self,
        source: ExecutableCatalogSource,
        model_ids: frozenset[str],
        *,
        admitted: AdmittedModels | None = None,
        admission_source: ModelAdmissionSource | None = None,
        on_admitted: Callable[[], None] | None = None,
    ) -> None:
        self._source = source
        self._model_ids = model_ids
        self._admitted = admitted if admitted is not None else AdmittedModels()
        parameter_source = source.model_parameter_source
        self._model_parameter_source = (
            None
            if parameter_source is None
            else ExecutableModelParameterSource(
                parameter_source,
                model_ids,
                admitted=self._admitted,
                admission_source=admission_source,
                on_admitted=on_admitted,
            )
        )

    @property
    def counters(self) -> CacheCounters | None:
        return self._source.counters

    @property
    def entry_count(self) -> int:
        return self._source.entry_count

    @property
    def admitted_model_ids(self) -> tuple[str, ...]:
        """The overlay's ids — what the App injects into a run's env (OME-880)."""
        return self._admitted.ids

    async def fetch(self, credential: Credential) -> ModelCatalog:
        catalog = await self._source.fetch(credential)
        data = catalog.body.get("data")
        # WHY this one raises but a bad ENTRY does not: a `data` that is not a list cannot be
        # projected at all, so there is no honest answer to give. A single malformed entry has
        # one — omit it. Raising there would let one odd upstream document turn discovery into a
        # 502 for every caller, and `CachedCatalog` serves stale-on-error, so a PERSISTENT
        # oddity would degrade into an outage once `stale_max_s` elapsed.
        if not isinstance(data, list):
            raise CatalogBadResponse("catalog data is not a list")
        # INVARIANT: membership is the whole filter. An entry that is not a mapping, or whose id
        # is absent or not a string, cannot equal a declared id — so the acceptance contract
        # ("every id returned is a declared route") holds without a separate shape check, and an
        # unknown future field on a RETAINED document still passes through untouched.
        #
        # WHY rewrite `id` here (OME-873): `self._model_ids` holds the REAL gateway ids (what
        # aigateway's own `data[].id` names, and what the membership check above compares
        # against), but what a caller should put in a url4 expression is the `~`-encoded route
        # id. `encode_route_id` is a no-op for the ids with no colon, so this applies uniformly.
        body = {
            **catalog.body,
            "data": [
                {**item, "id": encode_route_id(item["id"])}
                for item in data
                if isinstance(item, Mapping)
                and (item.get("id") in self._model_ids or item.get("id") in self._admitted)
            ],
        }
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return self._source.max_age_s(credential)

    async def aclose(self) -> None:
        await self._source.aclose()

    @property
    def model_parameter_source(self) -> ModelParameterSource | None:
        """The uncached Gateway detail source, guarded by this same executable route set."""

        return self._model_parameter_source


def _refusal_response(model: str, code: str | None, message: str | None) -> ModelParameterResponse:
    """A refusal rendered in aigateway's own 404 body shape (OME-880).

    WHY this shape and not a new one: caller-correctable gateway statuses already
    pass through this proxy verbatim as ``{"detail": {code, ...}}``, and the SDK
    decodes that one shape — so an admission refusal that wears it needs no new
    wire, no new REST mapping, and no second decoder.
    """
    detail = {
        "code": code or "model_not_admitted",
        "message": message or "the model was not admitted by the gateway",
        "provider": "openrouter",
        "model": model,
    }
    return ModelParameterResponse(
        status=404,
        content=json.dumps({"detail": detail}, separators=(",", ":")).encode(),
    )


class ExecutableModelParameterSource:
    """Reject model-parameter lookups outside the same declared execution world.

    OME-880: for an OpenRouter-shaped miss this source first asks the gateway to
    dynamically admit the model. The flow, in execution order: (1) declared →
    forward; (2) overlay member → forward, but a forwarded 404 means the gateway
    restarted and forgot its admissions, so the stale overlay entry is discarded
    and admission re-runs once — self-healing on the very next request instead
    of poisoning every retry until an ENGINE restart (review F1); (3) not a
    dynamically admissible shape, or no admission source wired → today's
    ``ModelNotInstalled``; (4) ask the gateway — a grant joins the overlay,
    fires ``on_admitted`` (catalog-cache invalidation, so ``GET /v1/models``
    lists it with a fresh ETag) and forwards; a refusal returns the
    gateway-shaped 404 body; an unanswerable gateway degrades to
    ``ModelNotInstalled``. All pre-spend.
    """

    def __init__(
        self,
        source: ModelParameterSource,
        model_ids: frozenset[str],
        *,
        admitted: AdmittedModels | None = None,
        admission_source: ModelAdmissionSource | None = None,
        on_admitted: Callable[[], None] | None = None,
    ) -> None:
        self._source = source
        self._model_ids = model_ids
        self._admitted = admitted if admitted is not None else AdmittedModels()
        self._admission_source = admission_source
        self._on_admitted = on_admitted

    async def fetch_model_parameters(
        self,
        credential: Credential,
        model: str,
    ) -> ModelParameterResponse:
        # `model` arrives as the caller wrote it — the same `~`-encoded id `GET /v1/models` just
        # advertised (OME-873). `self._model_ids` holds the REAL ids, and aigateway itself has
        # never heard of '~', so both the membership check and the forwarded call need the
        # decoded form; `ModelNotInstalled` echoes back what the caller actually sent.
        real_model = decode_route_id(model)
        if real_model in self._model_ids:
            return await self._source.fetch_model_parameters(credential, real_model)
        if real_model in self._admitted:
            response = await self._source.fetch_model_parameters(credential, real_model)
            if response.status != 404:
                return response
            # HEAL (review F1): a 404 for an OVERLAY id means the gateway restarted
            # and forgot the admission (its admitted set is deliberately in-memory).
            # The overlay must never contradict the gateway's latest answer, so the
            # stale entry is dropped and admission decides afresh — bounded to one
            # retry: whatever the re-admitted fetch returns is the answer.
            self._admitted.discard(real_model)
        return await self._admit_and_fetch(credential, model, real_model)

    async def _admit_and_fetch(
        self,
        credential: Credential,
        model: str,
        real_model: str,
    ) -> ModelParameterResponse:
        """Ask the gateway to admit ``real_model``, then forward on a grant."""
        if self._admission_source is None or not is_dynamically_admissible(real_model):
            raise ModelNotInstalled(model)
        answer = await self._admission_source.admit_model(credential, real_model)
        if answer.outcome == "refused":
            return _refusal_response(model, answer.code, answer.message)
        if answer.outcome != "admitted":
            # INVARIANT (graceful fallback): a gateway without the admit
            # endpoint leaves behavior byte-identical to today's.
            raise ModelNotInstalled(model)
        self._admitted.add(real_model)
        if self._on_admitted is not None:
            self._on_admitted()
        return await self._source.fetch_model_parameters(credential, real_model)


__all__ = ["ExecutableCatalog", "ExecutableCatalogSource", "ExecutableModelParameterSource"]
