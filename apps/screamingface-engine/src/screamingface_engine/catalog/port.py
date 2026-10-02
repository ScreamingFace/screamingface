"""Model-discovery ports shared by the cache, REST boundary, and AI Gateway adapter.

FEATURE: model-catalog discovery. ``GET /v1/models`` on screamingface-engine answers
"which models can I address?" by forwarding the caller's own verified identity
upstream and caching the result per caller.

STORY: as a client composing a url4 expression, I ask screamingface-engine which
model paths exist before I reference one, instead of guessing and failing at run
time.

Defines the shared identity, the cached model-list contract, the uncached model-parameter
contract, and the RFC 9457-style error hierarchy. ``CatalogSource`` and
``ModelParameterSource`` stay separate so a catalog-only adapter is not forced to pretend it can
serve details.

AIDEV-NOTE: this module is a dependency-free leaf on purpose — no httpx, no FastAPI. Both the
adapter (which speaks HTTP) and the cache (which speaks to nothing) import it, and the route maps
its error types onto RFC 9457 problems. Keep transport concerns out of here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# WHY 32 hex (128 bits) for the cache key: it must be collision-free across concurrent callers,
# since a collision would serve one caller another's catalog. 16 hex for the ETag is fine by
# contrast — an ETag collision only costs a spurious 304, never a cross-caller leak.
_KEY_LENGTH = 32
_ETAG_LENGTH = 16

# WHY a NUL delimiter: without one, ("ab", "c") and ("a", "bc") would hash to the same key. NUL
# cannot appear in an HTTP header value, so it can never occur inside either component.
_KEY_SEPARATOR = "\x00"


@dataclass(frozen=True, slots=True)
class Credential:
    """A caller-supplied aigateway identity, plus the cache key derived from it.

    The caller is described by the verified ``identity`` headers Envoy injects (deployed), or by
    nothing at all (local, where aigateway runs ``disabled`` and every caller is anonymous). No
    bearer token is carried: neither aigateway mode this app targets reads ``Authorization``.

    INVARIANT: an empty identity is a legitimate value, and it gets its OWN cache key — anonymous
    responses must never be served to an identified caller, or vice versa.
    """

    key: str
    identity: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def derive(
        cls,
        identity: Mapping[str, str] | None = None,
    ) -> Credential:
        """Build a credential and its cache key from the caller's verified identity.

        INVARIANT: the key is a *digest*, and it is fixed-length — so per-entry memory cannot be
        chosen by whoever sends the headers (spec §7).

        INVARIANT: the identity is part of the key material. Two callers distinguished ONLY by
        their verified email must not share a cache entry, or one principal is served the other's
        catalog.
        """
        # WHY: NUL-separate every component before hashing so distinct tuples can't collide by
        # concatenating to the same string. The identity is sorted so an equal mapping always
        # yields an equal key regardless of insertion order.
        identity = dict(identity or {})
        identity_material = _KEY_SEPARATOR.join(
            f"{name}={identity[name]}" for name in sorted(identity)
        )
        # Preserve the former selector-less key material so an in-process deployment does not
        # invalidate every catalog entry merely because the retired field disappeared.
        material = f"{_KEY_SEPARATOR}{identity_material}".encode()
        return cls(
            key=hashlib.sha256(material).hexdigest()[:_KEY_LENGTH],
            identity=identity,
        )


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """One fetched catalog document plus its derived ETag.

    The AI Gateway adapter fills this with the upstream body verbatim. The Engine projection
    later replaces only ``data`` with the declared-route intersection and derives a new ETag.
    """

    body: dict[str, object]
    etag: str


@dataclass(frozen=True, slots=True)
class ModelParameterResponse:
    """One validated JSON response from AI Gateway, retaining its wire representation."""

    status: int
    content: bytes


def compute_etag(body: dict[str, object]) -> str:
    """A strong ETag over the catalog's content (spec §5.2).

    INVARIANT: determined by content, not by dict ordering — ``sort_keys`` (and compact
    separators) is what makes a re-fetch of an unchanged catalog produce the same validator, so a
    cache refresh does not needlessly invalidate every client's copy.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:_ETAG_LENGTH]


class CatalogError(Exception):
    """Base for catalog failures, carrying the HTTP mapping the route should apply.

    WHY the status lives on the exception: the route then needs no ``isinstance`` ladder, so adding
    a failure mode does not mean editing the route. Subclasses override the three attributes.
    """

    status = 502
    title = "Bad Gateway"
    detail = "the model catalog could not be retrieved"


class CatalogRejected(CatalogError):
    """Upstream refused the credential.

    INVARIANT: the detail stays generic. This endpoint does not verify the credential itself, so a
    caller learning that a token was *recognised but refused* would be an oracle over this
    deployment's aigateway configuration.
    """

    status = 401
    title = "Unauthorized"
    detail = "aigateway rejected the supplied credential"


class CatalogBadResponse(CatalogError):
    """The upstream response was malformed, non-JSON, or otherwise unusable."""

    status = 502
    title = "Bad Gateway"
    detail = "aigateway returned an unusable model catalog"


class ModelParameterBadResponse(CatalogBadResponse):
    """The detailed parameter response was not safe to proxy."""

    detail = "aigateway returned an unusable model-parameter contract"


class ModelNotInstalled(CatalogError):
    """The requested model is absent from this Engine's declared execution world."""

    status = 404
    title = "Not Found"
    detail = "the model is not installed on this Engine"


class CatalogUnavailable(CatalogError):
    """The upstream request timed out."""

    status = 504
    title = "Gateway Timeout"
    detail = "aigateway did not respond in time"


@runtime_checkable
class CatalogSource(Protocol):
    """Anything that can produce a catalog for a credential.

    Implemented by the aigateway adapter (``AigatewayCatalogSource``) and — as a
    decorator over another source — by
    :class:`~screamingface_engine.catalog.cache.CachedCatalog`, which is what lets the
    route depend on one type whether or not caching is in play.
    """

    async def fetch(self, credential: Credential) -> ModelCatalog: ...


@runtime_checkable
class ModelParameterSource(Protocol):
    """Anything that can fetch one model-parameter contract."""

    async def fetch_model_parameters(
        self,
        credential: Credential,
        model: str,
        *,
        traceparent: str | None = None,
    ) -> ModelParameterResponse:
        """Fetch one contract; ``traceparent`` is the inbound caller's, or ``None`` to send none.

        INVARIANT (OME-1134): the trace is a per-call ARGUMENT, never a ``Credential`` field —
        ``Credential`` derives the catalog cache key, and a per-request value there would give
        every request its own cache entry.
        """
        ...


__all__ = [
    "CatalogBadResponse",
    "CatalogError",
    "CatalogRejected",
    "CatalogSource",
    "CatalogUnavailable",
    "Credential",
    "ModelCatalog",
    "ModelNotInstalled",
    "ModelParameterBadResponse",
    "ModelParameterResponse",
    "ModelParameterSource",
    "compute_etag",
]
