"""Engine wiring, the pure half: mounts -> the three discovery documents.

`wellknown.py` builds one document at a time. This is what a request actually needs: the
body, its ETag, and how long it may be cached — for ONE caller, because the enums are
narrowed per caller and so the documents are too.

Deliberately NOT a cache and NOT a server. It composes; the ASGI wrapper in
`url4.cli._serve` serves what it returns. Keeping the composition free of both means the
three documents are testable without binding a port, which is the same reason
`url4.peer.server` is plain ASGI rather than a framework.

`SupportsMaxAge` is the seam for a caller-dependent TTL. Nothing in `url4 serve` varies it
today, so `Discovery` takes a flat `max_age_s`; the protocol stays because a node that
fronts entitlement-scoped endpoints will need it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from url4.discovery.wellknown import (
    Mount,
    build_bundle,
    build_card,
    canonical,
    config_url,
    mount_resource,
)


class MountNotFound(LookupError):
    """No mount by that name — a `404`, not a failure to compose."""


@dataclass(frozen=True)
class Document:
    """One discovery response: what to send, and how it may be cached."""

    body: dict
    etag: str
    max_age_s: int
    private: bool

    def headers(self) -> dict[str, str]:
        """The full header set, including the ETag the route compares against.

        `Vary` is unconditional and `private` follows the caller's identity — see
        `wellknown.discovery_headers` for why both, rather than only the narrowed variant.
        """
        from url4.discovery.wellknown import discovery_headers

        return {
            **discovery_headers(identity_present=self.private, ttl_s=self.max_age_s),
            "ETag": f'"{self.etag}"',
        }


#: Resolves the mounts as THIS caller sees them — each carrying the schema its endpoint
#: served for that caller, with the enum already narrowed. Injected, so this module never
#: learns how to fetch (httpx, the mount table, the health probe are all the engine's).
MountResolver = Callable[[str | None], Awaitable[Sequence[Mount]]]


class SupportsMaxAge(Protocol):
    """The engine's catalog service already knows the per-caller TTL; reuse it."""

    def max_age_s(self, caller: str | None) -> int: ...


def etag_of(body: dict) -> str:
    """A strong validator over the canonical bytes.

    Derived from the BODY, not from a timestamp or a counter: two callers whose narrowed
    enums happen to match get the same ETag and share a cache entry, and a re-fetch that
    changed nothing does not invalidate anyone's copy.
    """
    return hashlib.sha256(canonical(body)).hexdigest()[:32]


class Discovery:
    """Composes the card, the bundle, and each mount's schema for one caller."""

    def __init__(
        self,
        origin: str,
        resolve: MountResolver,
        *,
        max_age_s: int = 300,
        node_uri: str | None = None,
    ) -> None:
        self._origin = origin.rstrip("/")
        self._resolve = resolve
        self._max_age_s = max_age_s
        self._node_uri = node_uri

    async def mounts_for(self, caller: str | None) -> Sequence[Mount]:
        """The mounts as this caller sees them, each with the schema served to THEM.

        Exposed because request-time enforcement needs the same per-caller view the
        documents are built from: the enum a value is judged against must be the one the
        caller was shown, or discovery and enforcement disagree about what is allowed.
        """
        return list(await self._resolve(caller))

    async def card(self, caller: str | None) -> Document:
        mounts = list(await self._resolve(caller))
        return self._document(build_card(self._origin, mounts, node_uri=self._node_uri), caller)

    async def bundle(self, caller: str | None) -> Document:
        mounts = list(await self._resolve(caller))
        return self._document(build_bundle(self._origin, mounts), caller)

    async def mount(self, caller: str | None, name: str) -> Document:
        """One mount's schema, byte-identical to the copy inside the bundle.

        Identical BY CONSTRUCTION, not by assertion: `build_bundle` embeds what
        `mount_resource` returns, so there is one construction used twice.
        """
        for mount in await self._resolve(caller):
            if mount.name == name and mount.served_schema is not None:
                return self._document(mount_resource(self._origin, mount), caller)
        raise MountNotFound(name)

    def _document(self, body: dict, caller: str | None) -> Document:
        return Document(
            body=body,
            etag=etag_of(body),
            max_age_s=self._max_age_s,
            private=caller is not None,
        )

    @property
    def bundle_id(self) -> str:
        return config_url(self._origin)


__all__ = ["Discovery", "Document", "MountNotFound", "MountResolver", "SupportsMaxAge", "etag_of"]
