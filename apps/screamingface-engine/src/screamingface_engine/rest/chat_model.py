"""Stage 4 of POST /v1/chat/completions: the model value becomes the recipe of the run.

CC-S1: a value that starts with "(" after white space is a URL4; it runs as built after the
recipe check (with no tools, owner answer Q6). Any other value is a gateway model id: it becomes
the one-model recipe (plan D4), and the model-parameters lookup must know it. A positive lookup
is kept for 60 s for the same caller and id; a "not known" answer is never kept.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from screamingface_engine.catalog.port import (
    CatalogError,
    Credential,
    ModelNotInstalled,
    ModelParameterSource,
)
from screamingface_engine.chat.recipe import (
    RecipeRefusal,
    check_recipe,
    is_recipe_value,
    one_model_recipe,
)
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.world.models.registry import decode_route_id

__all__ = [
    "CATALOG_RETRY_AFTER_S",
    "MODEL_LOOKUP_TTL_S",
    "ModelLookupCache",
    "recipe_for",
]

MODEL_LOOKUP_TTL_S = 60.0
CATALOG_RETRY_AFTER_S = 5
_MAX_ENTRIES = 4096

type _Key = tuple[str, str]


class ModelLookupCache:
    """Positive model lookups, per (caller key, model value as sent), for `ttl_s` seconds."""

    def __init__(
        self,
        ttl_s: float = MODEL_LOOKUP_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._expiry: dict[_Key, float] = {}

    def known(self, key: _Key) -> bool:
        """Whether a positive answer for `key` is still fresh."""
        expires = self._expiry.get(key)
        if expires is not None and expires <= self._clock():
            del self._expiry[key]
            expires = None
        return expires is not None

    def keep(self, key: _Key) -> None:
        """Keep a positive answer for `key`."""
        now = self._clock()
        if len(self._expiry) >= _MAX_ENTRIES:
            # INVARIANT: bounded memory; the drop of fresh entries costs only extra lookups.
            self._expiry = {k: t for k, t in self._expiry.items() if t > now}
            if len(self._expiry) >= _MAX_ENTRIES:
                self._expiry.clear()
        self._expiry[key] = now + self._ttl_s


async def recipe_for(
    model: str,
    *,
    identity: Mapping[str, str] | None,
    source: ModelParameterSource | None,
    cache: ModelLookupCache,
    traceparent: str | None,
) -> str:
    """The recipe the run evaluates for `model`, or the ChatError of the refusal."""
    if is_recipe_value(model):
        return _checked_recipe(model)
    recipe = _one_model(model)
    await _look_up(model, identity, source, cache, traceparent)
    return recipe


def _checked_recipe(model: str) -> str:
    """CC-S13 to CC-S15: the recipe check with no tools; the URL4 runs as the client sent it."""
    try:
        check_recipe(model, with_tools=False)
    except RecipeRefusal as exc:
        raise ChatError(400, exc.code, exc.message, param="model") from None
    return model


def _one_model(model: str) -> str:
    """D4: the one-model recipe; a `~` id from GET /v1/models is decoded first (C3)."""
    try:
        return one_model_recipe(decode_route_id(model))
    except ValueError:
        raise ChatError(404, "model_not_found", param="model") from None


async def _look_up(
    model: str,
    identity: Mapping[str, str] | None,
    source: ModelParameterSource | None,
    cache: ModelLookupCache,
    traceparent: str | None,
) -> None:
    """CC-S1, CC-S12: the catalogue must know the id as the client sent it."""
    if source is None:
        # WHY no Retry-After: only an operator can configure a gateway (owner answer Q5).
        raise ChatError(503, "catalog_unavailable")
    credential = Credential.derive(identity)
    key = (credential.key, model)
    if cache.known(key):
        return
    try:
        answer = await source.fetch_model_parameters(credential, model, traceparent=traceparent)
    except ModelNotInstalled:
        raise ChatError(404, "model_not_found", param="model") from None
    except CatalogError:
        raise ChatError(
            503,
            "catalog_unavailable",
            retry_after=CATALOG_RETRY_AFTER_S,
            should_retry=True,
        ) from None
    if not 200 <= answer.status < 300:
        raise ChatError(404, "model_not_found", param="model")
    cache.keep(key)
