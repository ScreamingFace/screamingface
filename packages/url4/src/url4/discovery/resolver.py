"""The mount table, resolved: `url4.json` mounts -> the `Mount`s the builders take.

This is the only module that knows a mount has to be FETCHED. It does not know how:
``fetch`` is injected as a coroutine taking an absolute URL and returning the body, so this
package stays stdlib-only and ``url4.io.http`` remains the single module importing httpx.

Two mount kinds, and the difference is who composed the endpoint:

* **composed** — the node launched it from a ``plugin`` FQN, so it knows the address and
  fetches both documents. A composed mount that answers becomes ``ok``.
* **foreign** — already running, named by ``upstream``. The node did not compose it, so
  per the design it is listed ``unavailable`` and stays out of ``$defs``. It is still
  ANNOUNCED: a client needs to know the path exists and is not currently offered.

A mount that fails its probe degrades to ``unavailable`` rather than raising. Discovery
that 500s because one endpoint is down tells a client nothing about the four that are up.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from url4.discovery.wellknown import (
    CAPABILITIES_PATH,
    CONFIG_PATH,
    Mount,
    ProcessorType,
    read_endpoint_card,
)

#: Fetch one absolute URL, returning the response body. Raises on any failure — the
#: resolver treats every exception as a failed probe, so the adapter need not classify.
Fetch = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class MountSpec:
    """One entry of `url4.json`'s ``mounts``, after shape checking.

    ``endpoint_id`` is what the card calls the processor. For a composed mount it is the
    plugin's last path segment; a foreign mount has no plugin, so it falls back to the
    mount name. Both are stable for a given table, which is what lets a client correlate
    two mounts of the SAME plugin at different paths.
    """

    path: str
    endpoint_id: str
    upstream: str | None = None
    foreign: bool = False

    @property
    def composed(self) -> bool:
        return not self.foreign and self.upstream is None


class MountTableError(ValueError):
    """A mount table that cannot be read — raised before bind, never per request."""


def read_mount_table(mounts: Mapping[str, Any] | None) -> tuple[MountSpec, ...]:
    """Validate ``url4.json``'s ``mounts`` into specs. Fail-fast, at startup.

    The catalog (`url4-node.schema.json`) already constrains this shape, but a node must
    not depend on having been validated: `url4 serve` can be pointed at any file.
    """
    if not mounts:
        return ()
    if not isinstance(mounts, Mapping):
        raise MountTableError(f"mounts must be an object, got {type(mounts).__name__}")

    specs: list[MountSpec] = []
    for raw_path, entry in mounts.items():
        path = str(raw_path)
        if not path.startswith("/") or "/" in path[1:] or len(path) < 2:
            raise MountTableError(
                f"mount key {path!r} must be a single leading-slash segment — keys are "
                "PUBLIC PATHS, which is what makes a routing collision inexpressible"
            )
        if not isinstance(entry, Mapping):
            raise MountTableError(f"mount {path!r} must be an object")

        plugin = entry.get("plugin")
        upstream = entry.get("upstream")
        foreign = bool(entry.get("foreign", False)) or upstream is not None

        # INVARIANT: a composed mount names a plugin and never an upstream — the node
        # learns the address by launching it. A foreign mount is exactly the reverse.
        # Accepting both would leave "which address wins" undefined at fetch time.
        if plugin is not None and upstream is not None:
            raise MountTableError(
                f"mount {path!r} declares both `plugin` and `upstream` — a composed mount "
                "learns its address by launching, a foreign one is told it"
            )
        if plugin is None and upstream is None:
            raise MountTableError(f"mount {path!r} declares neither `plugin` nor `upstream`")

        specs.append(
            MountSpec(
                path=path,
                endpoint_id=_endpoint_id(plugin, path),
                upstream=None if upstream is None else str(upstream),
                foreign=foreign,
            )
        )
    return tuple(specs)


def _endpoint_id(plugin: object, path: str) -> str:
    """The processor id a card announces.

    The FQN's last segment, with any ``@ref`` dropped: `.../apps/node-codex@v1.2.0` is the
    `node-codex` endpoint whether it was pinned to a tag, a branch or a sha. Deriving it
    from the ref would make the same plugin announce a different id per deployment.
    """
    if plugin is None:
        return path[1:]
    text = str(plugin).split("@")[0].rstrip("/")
    return text.rsplit("/", 1)[-1] or path[1:]


class TableResolver:
    """Resolves a mount table into `Mount`s for one caller.

    Per caller, because the schema an endpoint serves is narrowed by the caller's
    entitlements — two callers get different documents from the same table, so the
    resolution cannot be shared between them. Caching that is the composition root's job.
    """

    def __init__(
        self,
        specs: Sequence[MountSpec],
        fetch: Fetch,
        *,
        base_url: str = "",
        timeout_s: float = 10.0,
    ) -> None:
        self._specs = tuple(specs)
        self._fetch = fetch
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def __call__(self, caller: str | None) -> Sequence[Mount]:
        """Probe every mount concurrently; a failure is `unavailable`, never an error."""
        results = await asyncio.gather(
            *(self._resolve_one(spec) for spec in self._specs),
            return_exceptions=False,
        )
        return results

    async def _resolve_one(self, spec: MountSpec) -> Mount:
        if not spec.composed:
            # Announced, deliberately without a schema: the node never composed it, so it
            # cannot vouch for what the endpoint serves.
            return Mount(path=spec.path, endpoint_id=spec.endpoint_id, served_schema=None)

        origin = self._origin_for(spec)
        schema = None
        if await self._healthy(origin):
            schema = await self._fetch_json(f"{origin}{CONFIG_PATH}")
            if not isinstance(schema, dict):
                schema = None
        return Mount(
            path=spec.path,
            endpoint_id=spec.endpoint_id,
            served_schema=schema,
            type=ProcessorType.URL4_DELEGATE,
        )

    def _origin_for(self, spec: MountSpec) -> str:
        """Where this mount's endpoint answers.

        A composed endpoint serves the PUBLIC path itself (`endpoint.path` is set from the
        mount key at launch), so forwarding is verbatim and the origin is the node's own
        base plus that path — there is no rewrite to undo.
        """
        return f"{self._base_url}{spec.path}"

    async def _healthy(self, origin: str) -> bool:
        """The endpoint's own card doubles as the health probe (§11.4).

        A card that does not parse, or announces a version this node does not speak, is a
        FAILED PROBE rather than an exception — `read_endpoint_card` returns None and the
        mount degrades, which is the behaviour a client can act on.
        """
        card = read_endpoint_card(await self._fetch_json(f"{origin}{CAPABILITIES_PATH}"))
        return card is not None and card.healthy

    async def _fetch_json(self, url: str) -> Any:
        """Fetch and parse, or None. Every failure mode collapses to one unavailable."""
        try:
            async with asyncio.timeout(self._timeout_s):
                body = await self._fetch(url)
        except Exception:  # noqa: BLE001 - any failure is a failed probe, by design
            return None
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            return None


__all__ = ["Fetch", "MountSpec", "MountTableError", "TableResolver", "read_mount_table"]
