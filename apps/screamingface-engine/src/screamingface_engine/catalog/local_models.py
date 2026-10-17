"""Ephemeral local-provider models mirrored from the configured AIGateway catalog."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from threading import Lock

from screamingface_engine.catalog.port import CatalogSource, Credential, ModelCatalog
from screamingface_engine.world.models.registry import encode_route_id, is_route_legal


class LocalModels:
    """One atomically replaced raw-id snapshot plus its URL4 route projection."""

    def __init__(self, *, prefixes: tuple[str, ...]) -> None:
        self._prefixes = frozenset(prefixes)
        self._raw = frozenset[str]()
        self._lock = Lock()

    def __contains__(self, model_id: object) -> bool:
        with self._lock:
            return model_id in self._raw

    @property
    def raw_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._raw))

    @property
    def route_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(encode_route_id(model_id) for model_id in self._raw))

    def replace(self, model_ids: Iterable[object]) -> None:
        selected = frozenset(
            model_id
            for model_id in model_ids
            if isinstance(model_id, str) and self.accepts(model_id)
        )
        # INVARIANT: one assignment is the linearization point. Readers see the
        # complete prior or complete next catalog, never a partially refreshed set.
        with self._lock:
            self._raw = selected

    def accepts(self, model_id: str) -> bool:
        """Whether a raw id belongs to this local overlay's route namespace."""

        provider, separator, _model = model_id.partition("/")
        if not separator or provider not in self._prefixes or "~" in model_id:
            return False
        return is_route_legal(encode_route_id(model_id))


class LocalCatalogSource:
    """Update local models only when a real upstream catalog fetch succeeds."""

    def __init__(self, source: CatalogSource, models: LocalModels) -> None:
        self._source = source
        self._models = models
        self._refresh_lock = asyncio.Lock()

    async def fetch(self, credential: Credential) -> ModelCatalog:
        # WHY serialize across caller identities: CachedCatalog coalesces per caller,
        # while this deployment-local snapshot has one authoritative refresh order.
        async with self._refresh_lock:
            catalog = await self._source.fetch(credential)
            data = catalog.body.get("data")
            if isinstance(data, list):
                self._models.replace(item.get("id") for item in data if isinstance(item, dict))
            return catalog


__all__ = ["LocalCatalogSource", "LocalModels"]
