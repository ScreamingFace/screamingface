"""The declared model world as code — which gateway ids this Engine may route.

WHY code rather than the ``[[aigateway.models]]`` TOML array it replaces: the list must track
aigateway's compiled plugin seeds, which grew from 25 to 113 ids in one epic (OME-815) with
nothing in CI reporting the drift. Authoring it here makes the list type-checked, lets the colon
partition below be one predicate instead of 29 silent omissions, and gives the drift guard a
single object to compare against aigateway's source.

This module mirrors ``screamingface_engine/benchmarks/registry.py``: a validated
immutable registry, one composition root beside it (``builtins.py``), and all
validation at construction — before the first paid request.

INVARIANT: this module imports nothing from ``screamingface_engine``. ``world_config``
imports the charset from here and ``builtins`` imports the seeds, so any import back
up would be a cycle.

AIDEV-NOTE: a seed declares SLUGS, not ids. :meth:`ProviderSeed.ids` applies aigateway's one
canonical rule. Keep it that way — each seed file then stays a byte-comparable mirror of the
plugin list it tracks, which is what ``test_declared_models_match_aigateway.py`` asserts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

ROUTE_ID_RE = re.compile(r"[A-Za-z0-9\-_.~]+(?:/[A-Za-z0-9\-_.~]+)*", re.ASCII)
"""A gateway id that is also renderable as a URL4 expression path (url4 spec §8).

INVARIANT: this is the ONE definition of the charset. ``world_config`` imports it rather than
keeping a second copy, because a route path is exactly ``"/" + id`` and the two rules cannot be
allowed to disagree.
"""

_COLON = ":"
_TILDE = "~"


def is_route_legal(model_id: str) -> bool:
    """Whether ``model_id`` can be a url4 route path, segment for segment."""
    return ROUTE_ID_RE.fullmatch(model_id) is not None


def encode_route_id(model_id: str) -> str:
    """The url4-route form of a gateway id: ``:`` escaped as ``~`` (OME-873).

    INVARIANT: a no-op on any id with no colon, so callers may apply it unconditionally to
    every declared id rather than branching on "is this one of the 29". The inverse of
    :func:`decode_route_id`.
    """
    return model_id.replace(_COLON, _TILDE)


def decode_route_id(route_id: str) -> str:
    """The real gateway id a route path names: ``~`` reverted to ``:`` (OME-873).

    INVARIANT: a no-op on any route id with no tilde. Safe to call unconditionally at the
    point a real request or comparison against aigateway's own catalog is made, because ``~``
    is reserved exclusively for this escape (see the seed-validation guard below) — no
    routable id may carry a literal one.
    """
    return route_id.replace(_TILDE, _COLON)


def canonical_id(provider: str, slug: str) -> str:
    """The public id aigateway advertises for ``slug``.

    INVARIANT: mirrors ``aigateway.core.model_capabilities.canonical_model_id`` — keep the slug
    when it already begins with ``<provider>/``, otherwise prefix it. There is NO per-provider
    exemption; OME-795 was caused by a hand-written prefix table that guessed ``""`` for
    Anthropic, so all five Anthropic routes vanished from the projected catalog.
    """
    prefix = f"{provider}/"
    return slug if slug.startswith(prefix) else f"{prefix}{slug}"


@dataclass(frozen=True, slots=True)
class ProviderSeed:
    """One aigateway provider's compiled model list, authored as slugs."""

    provider: str
    slugs: tuple[str, ...]

    def ids(self) -> tuple[str, ...]:
        """The canonical gateway ids these slugs name."""
        return tuple(canonical_id(self.provider, slug) for slug in self.slugs)


class ModelRegistry:
    """One immutable, validated set of gateway ids this Engine declares.

    FEATURE: the declared world — what a url4 expression may address, and what
    ``GET /v1/models`` may advertise.
    """

    __slots__ = ("_aigateway_only", "_routable")

    def __init__(self, seeds: Iterable[ProviderSeed] = ()) -> None:
        routable: set[str] = set()
        aigateway_only: set[str] = set()
        for seed in seeds:
            # WHY iterate slugs rather than `seed.ids()`: canonicalisation prefixes the slug, so
            # by the time an id exists an empty slug reads as `"openrouter/"` and a leading-slash
            # slug as `"openrouter//openai/…"`. Neither trips its own check any more. Both stages
            # have to be validated, so both have to be in scope.
            for slug in seed.slugs:
                _validate_slug(slug)
                model_id = canonical_id(seed.provider, slug)
                _validate(model_id)
                if model_id in routable or model_id in aigateway_only:
                    raise ValueError(f"duplicate model id {model_id!r}")
                if _COLON in model_id:
                    aigateway_only.add(model_id)
                else:
                    routable.add(model_id)
        self._routable = frozenset(routable)
        self._aigateway_only = frozenset(aigateway_only)

    @property
    def routable(self) -> frozenset[str]:
        """Ids that become url4 routes."""
        return self._routable

    @property
    def aigateway_only(self) -> frozenset[str]:
        """Ids aigateway serves that carry a ``:`` and so cannot be a url4 route VERBATIM.

        WHY the name survives OME-873: this partition is a pure function of the RAW id (see
        `test_the_unroutable_ids_are_exactly_the_colon_bearing_ones`) and stays so on purpose —
        `encode_route_id` (this module) is what makes these routable, applied one layer up in
        `world_config._merge`, not a change to this classification. An id here still can never
        be routed under its own, real form.
        """
        return self._aigateway_only

    @property
    def all_ids(self) -> frozenset[str]:
        """Every declared id, routable or not."""
        return self._routable | self._aigateway_only

    def __len__(self) -> int:
        return len(self._routable) + len(self._aigateway_only)


def _validate_slug(slug: str) -> None:
    """Raise unless ``slug`` can be canonicalised — checked BEFORE the provider prefix is added."""
    if not slug:
        raise ValueError("empty model id")
    if slug.startswith("/"):
        raise ValueError(
            f"model id {slug!r} must not start with '/' — the route path is derived as '/' + id"
        )


def _validate(model_id: str) -> None:
    """Raise unless the canonical ``model_id`` is a well-formed gateway id.

    WHY a colon is tolerated here but every other illegal character is not: the colon is a known
    grammar limit with 29 real ids behind it, handled by the partition. Anything else is a typo,
    and filing a typo under ``aigateway_only`` would hide it from the equality guard forever.

    WHY a literal '~' is refused even though it IS in `ROUTE_ID_RE`'s charset (OME-873): '~' is
    reserved exclusively as `encode_route_id`'s colon-escape. A legitimate id carrying one would
    be indistinguishable from an encoded colon id and could collide with one on decode.
    """
    if _TILDE in model_id:
        raise ValueError(
            f"model id {model_id!r} contains '~', which is reserved to encode a colon-bearing "
            "id as a url4 route (see encode_route_id) — a real gateway id may never carry one"
        )
    if not is_route_legal(model_id.replace(_COLON, "")):
        raise ValueError(
            f"model id {model_id!r} is not a valid URL4 expression path — each segment may "
            "contain only ASCII letters, digits, '-', '_', '.', or '~'"
        )


EMPTY_MODEL_WORLD = ModelRegistry()
"""A world declaring nothing — the parallel of
:data:`screamingface_engine.benchmarks.EMPTY_BENCHMARKS`."""

__all__ = [
    "EMPTY_MODEL_WORLD",
    "ROUTE_ID_RE",
    "ModelRegistry",
    "ProviderSeed",
    "canonical_id",
    "decode_route_id",
    "encode_route_id",
    "is_route_legal",
]
