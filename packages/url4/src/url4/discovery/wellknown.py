"""Slice C — the node's `.well-known` discovery surface.

Two documents, served from the node origin:

    GET /.well-known/url4-capabilities          the card: one entry per mount
    GET /.well-known/url4-config                the bundle: every mounted schema
    GET /.well-known/url4-config/<mount>        one mount's schema, alone

An endpoint serves a third `.well-known` document too, the policy registry — see
`POLICY_PATH`. This package reserves the path and models nothing else about it; its
contents are Part H's, not OME-1183's.

Framework-free on purpose. Everything here is pure functions over dicts, so the FastAPI
wiring in the engine is a thin adapter and the contract itself is testable without a
server — the same posture `url4.peer.server` takes with its plain-ASGI app.

NAMING (D2, decided 2026-09-15): `url4-` everywhere, in the paths AND in the document
fields. `abc_version` / `abc_delegate` in the generated worked set are url4's OLD NAME —
Parts C-I of the spec still carry `abc://` and `ABC-*` while Parts A/B were already
renamed. `url4_delegate` also keeps the contrast Part G §27.3 draws with `http_delegate`:
a delegate reached over the url4 protocol, versus one reached over plain HTTP.

WHAT "BYTE-IDENTICAL" CAN MEAN (§11.3)
--------------------------------------
The spec says the node embeds each schema keeping its own absolute `$id` — "the only
thing the node changes" — and that `GET .../url4-config/<mount>` returns that identical
resource alone.

Read literally against the UPSTREAM response, that is unsatisfiable: rewriting `$id` IS a
change, so the bytes the endpoint sent cannot survive. The guarantee that is both
achievable and useful is between the node's own two copies:

    canonical(bundle["$defs"][name])  ==  canonical(mount_resource(...))

i.e. a client that resolves a `$ref` offline out of the bundle gets exactly what fetching
the standalone URL would have given it. `canonical` is the single serialisation both go
through, and it does NOT sort keys — reordering would be a second change, on top of the
one the spec permits. `test_embedding_changes_only_the_id` pins the other half: against
the document the endpoint actually served, `$id` really is the only difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CAPABILITIES_PATH = "/.well-known/url4-capabilities"
CONFIG_PATH = "/.well-known/url4-config"

#: The POLICY REGISTRY (url4 spec Part H §30.2, spelled `abc-policy` there — renamed here
#: by D2 like everything else).
#:
#: RESOLVED 2026-09-15 (owner), in two steps. First: where OME-1183 and the url4 spec
#: disagreed, THE SPEC WINS. OME-1183 declared an endpoint's three paths "exhaustive"; the
#: spec defines a further `.well-known` document, so "exhaustive" was wrong. Second: the
#: owner placed it on the ENDPOINT, correcting an earlier inference of mine that put it on
#: the node because the policy registry is what a *source* publishes and an endpoint is a
#: function. It is the endpoint's.
#:
#: SO AN ENDPOINT SERVES FOUR PATHS, not three:
#:
#:     GET <path>?q=…                        the function
#:     GET /.well-known/url4-capabilities    the card (also the health probe)
#:     GET /.well-known/url4-config          the schema
#:     GET /.well-known/url4-policy          the policy registry
#:
#: Two things OME-1183 rests on have to be revisited, and neither is cosmetic:
#:
#: 1. `serves.well_known` in the manifest meta-schema is a `const` two-element list. A
#:    `const` cannot be widened by a node or a manifest — the meta-schema itself has to
#:    change, or no conformant manifest can declare the path it now serves.
#:    `test_the_manifest_meta_schema_cannot_yet_declare_the_policy_path` pins this.
#: 2. "`writeOnly` is satisfied BY CONSTRUCTION, because no served surface returns values"
#:    was an argument FROM the closed three-path list. With a fourth path the argument no
#:    longer follows from the list alone; the policy document needs its own reason. It
#:    states data terms — permitted consumers, redistribution depth — not configuration,
#:    so the conclusion is very likely still true. But it is now a claim to check rather
#:    than a consequence of the surface being closed.
#:
#: This package RESERVES the path and models nothing else about it. Its contents belong to
#: Part H §30.2, which is not reachable from this repo.
POLICY_PATH = "/.well-known/url4-policy"

#: Every `.well-known` document url4 defines — and, since the policy registry is the
#: endpoint's, every one an endpoint serves.
WELL_KNOWN_PATHS = (CAPABILITIES_PATH, CONFIG_PATH, POLICY_PATH)

#: Kept as its own name because callers ask "what does an endpoint serve?", and that
#: question should not be answered by knowing the two happen to be equal today.
ENDPOINT_WELL_KNOWN = WELL_KNOWN_PATHS

#: The document's own version field, and its value.
VERSION_KEY = "url4_version"
URL4_VERSION = 1

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: The identity headers a narrowed enum depends on. A cache that ignores these would
#: serve one caller's model list to another (§8.3), so they are stated once, here.
IDENTITY_HEADERS = ("X-Profile", "X-User-Email")


class ProcessorType(StrEnum):
    """Part G §27.3's five processor types.

    The worked set only exercises two (`internal` on an endpoint card, `url4_delegate` on
    a node card), but the vocabulary is five, and a reader that accepts only what the
    examples happen to show will reject a conformant card.
    """

    INTERNAL = "internal"
    URL4_DELEGATE = "url4_delegate"
    HTTP_DELEGATE = "http_delegate"
    CODE = "code"
    FUNCTION = "function"


class Status(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Mount:
    """One mounted endpoint, as the node sees it after composing.

    ``served_schema`` is the document the ENDPOINT served at its own
    `/.well-known/url4-config` — per-caller enums already resolved. ``None`` means the
    node never fetched it (a foreign mount, or one that failed its health probe), which
    is exactly what makes the mount `unavailable` and keeps it out of `$defs`.
    """

    path: str
    endpoint_id: str
    served_schema: dict[str, Any] | None = None
    type: ProcessorType = ProcessorType.URL4_DELEGATE

    def __post_init__(self) -> None:
        if not self.path.startswith("/") or "/" in self.path[1:] or len(self.path) < 2:
            raise ValueError(f"mount path {self.path!r} must be a single leading-slash segment")

    @property
    def name(self) -> str:
        """The `$defs` key and the last URL segment — the path without its slash."""
        return self.path[1:]

    @property
    def status(self) -> Status:
        return Status.OK if self.served_schema is not None else Status.UNAVAILABLE


def canonical(value: Any) -> bytes:
    """The node's ONE serialisation. Key order is preserved, never sorted.

    Sorting would reorder an author's catalog, which is a change the spec does not permit
    the node to make — and it would make the embedded and standalone copies differ from
    the document the endpoint served for no reason a client could understand.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def config_url(origin: str, mount: Mount | None = None) -> str:
    """The absolute `$id` of the bundle, or of one mount's resource within it."""
    base = f"{origin.rstrip('/')}{CONFIG_PATH}"
    return base if mount is None else f"{base}/{mount.name}"


def embed(origin: str, mount: Mount) -> dict[str, Any]:
    """The mount's schema with its `$id` rewritten to the node-absolute one.

    The `$id` is REPLACED IN PLACE when it exists, so the key keeps its position and the
    document's shape is otherwise untouched. A schema arriving without an `$id` gets one
    inserted first, which is the only case where a key moves.
    """
    if mount.served_schema is None:
        raise ValueError(f"mount {mount.path} was never fetched — nothing to embed")
    absolute = config_url(origin, mount)
    if "$id" in mount.served_schema:
        return {
            key: (absolute if key == "$id" else value) for key, value in mount.served_schema.items()
        }
    return {"$id": absolute, **mount.served_schema}


def mount_resource(origin: str, mount: Mount) -> dict[str, Any]:
    """What `GET /.well-known/url4-config/<mount>` returns.

    The SAME function the bundle embeds, so the two cannot drift: there is one
    construction, used twice, rather than two that are asserted to agree.
    """
    return embed(origin, mount)


def build_bundle(origin: str, mounts: list[Mount], *, title: str | None = None) -> dict[str, Any]:
    """The compound document (2020-12 §9.3): `$ref`s by mount path, `$defs` by name.

    A mount the node never fetched is listed in `properties.endpoints` carrying
    `x-status: unavailable` and NO `$ref` — it is absent from `$defs` because there is
    nothing to embed. A `$ref` to a missing `$def` would be a dangling pointer that only
    fails when a client tries to resolve it.
    """
    endpoints: dict[str, Any] = {}
    defs: dict[str, Any] = {}
    for mount in mounts:
        if mount.status is Status.OK:
            endpoints[mount.path] = {"$ref": config_url(origin, mount)}
            defs[mount.name] = embed(origin, mount)
        else:
            endpoints[mount.path] = {"x-status": Status.UNAVAILABLE.value}
    bundle: dict[str, Any] = {
        "$schema": SCHEMA_DIALECT,
        "$id": config_url(origin),
        "title": title or f"{_authority(origin)} — configuration",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "endpoints": {
                "type": "object",
                "additionalProperties": False,
                "properties": endpoints,
            }
        },
    }
    if defs:
        bundle["$defs"] = defs
    return bundle


def build_card(
    origin: str,
    mounts: list[Mount],
    *,
    node_uri: str | None = None,
    status: Status = Status.OK,
) -> dict[str, Any]:
    """The node's capabilities card — the ONE URL a client hardcodes.

    Several mounts may share an `id`: the worked set mounts `anthropic` three times. They
    are three INSTANCES of one plugin, told apart by `path`, so `id` is deliberately not
    unique and nothing here treats it as a key.
    """
    return {
        VERSION_KEY: URL4_VERSION,
        "node": node_uri or f"url4://{_authority(origin)}",
        "status": status.value,
        "config_schema": CONFIG_PATH,
        "intent_processors": [
            {
                "id": mount.endpoint_id,
                "type": mount.type.value,
                "path": mount.path,
                "config_schema": f"{CONFIG_PATH}/{mount.name}",
                "status": mount.status.value,
            }
            for mount in mounts
        ],
    }


@dataclass(frozen=True)
class EndpointCard:
    """What the node reads back from an endpoint's own card.

    The card doubles as the health probe (§11.4), so this is the probe's parser: a
    document that does not parse, or announces a version this node does not speak, is a
    failed probe rather than an exception in the composer.
    """

    status: Status
    version: int
    node: str
    processors: tuple[dict[str, Any], ...]

    @property
    def healthy(self) -> bool:
        return self.status is Status.OK


def read_endpoint_card(doc: Any) -> EndpointCard | None:
    """Parse an endpoint's card, or ``None`` when it is not one this node can use."""
    if not isinstance(doc, dict) or doc.get(VERSION_KEY) != URL4_VERSION:
        return None
    raw = doc.get("status")
    if raw not in tuple(Status):
        return None
    processors = doc.get("intent_processors")
    return EndpointCard(
        status=Status(raw),
        version=URL4_VERSION,
        node=str(doc.get("node", "")),
        processors=tuple(processors) if isinstance(processors, list) else (),
    )


def discovery_headers(*, identity_present: bool, ttl_s: int) -> dict[str, str]:
    """The cache headers every discovery response carries (§8.3).

    `Vary` is unconditional. A response served WITHOUT identity headers is still a
    response whose body would differ WITH them, so a cache that only learned to vary on
    the narrowed variant would already have stored the anonymous one under a key that
    ignores identity — and would serve it to an identified caller.
    """
    visibility = "private" if identity_present else "public"
    return {
        "Content-Type": "application/json",
        "Vary": ", ".join(IDENTITY_HEADERS),
        "Cache-Control": f"{visibility}, max-age={ttl_s}",
    }


#: The keywords a per-caller variant is ALLOWED to change. Exactly one: the schema is a
#: projection of the discovery cache, and entitlement narrows the enum. Anything else
#: differing means two callers were handed two different documents.
#:
#: DECIDED 2026-09-15 (owner): `description` is NOT per-caller. Help text must read the
#: same for every caller; which variant you hold is already in the cache headers
#: (`private` vs `public`), not in a field's documentation.
#:
#: TODO: the shipped example files still vary `models.name.description` across the three
#: variants, so this strict set currently fails against them —
#: `test_more_than_the_enum_differs_between_the_three` records exactly that. Revisit once
#: the documents are regenerated: the test flips to asserting no difference, and this
#: TODO goes away. Worth re-validating then that no OTHER keyword has started to vary.
PER_CALLER_KEYWORDS = ("enum",)


def differences(
    left: Any, right: Any, *, ignore: tuple[str, ...] = PER_CALLER_KEYWORDS, path: str = ""
) -> list[str]:
    """Every path at which two schemas differ, skipping ``ignore``d keywords.

    Returns paths rather than a bool because "they differ" is not an actionable build
    failure — "they differ at `properties.models.properties.name.description`" is.
    """
    if isinstance(left, dict) and isinstance(right, dict):
        return _dict_differences(left, right, ignore, path)
    if isinstance(left, list) and isinstance(right, list):
        return _list_differences(left, right, ignore, path)
    return [path] if left != right else []


def _dict_differences(left: dict, right: dict, ignore: tuple[str, ...], path: str) -> list[str]:
    out: list[str] = []
    for key in sorted(set(left) | set(right)):
        if key in ignore:
            continue
        here = f"{path}.{key}" if path else key
        if key not in left or key not in right:
            out.append(here)
        else:
            out.extend(differences(left[key], right[key], ignore=ignore, path=here))
    return out


def _list_differences(left: list, right: list, ignore: tuple[str, ...], path: str) -> list[str]:
    if len(left) != len(right):
        return [path]
    out: list[str] = []
    for index, (one, other) in enumerate(zip(left, right, strict=True)):
        out.extend(differences(one, other, ignore=ignore, path=f"{path}[{index}]"))
    return out


def same_modulo_enums(
    left: Any, right: Any, *, ignore: tuple[str, ...] = PER_CALLER_KEYWORDS
) -> bool:
    """§18's build check: two per-caller variants of one catalog agree except the enums."""
    return not differences(left, right, ignore=ignore)


def _authority(origin: str) -> str:
    return origin.split("://", 1)[-1].rstrip("/")


__all__ = [
    "CAPABILITIES_PATH",
    "ENDPOINT_WELL_KNOWN",
    "CONFIG_PATH",
    "IDENTITY_HEADERS",
    "POLICY_PATH",
    "SCHEMA_DIALECT",
    "URL4_VERSION",
    "VERSION_KEY",
    "WELL_KNOWN_PATHS",
    "PER_CALLER_KEYWORDS",
    "EndpointCard",
    "Mount",
    "ProcessorType",
    "Status",
    "build_bundle",
    "build_card",
    "canonical",
    "config_url",
    "differences",
    "discovery_headers",
    "embed",
    "mount_resource",
    "read_endpoint_card",
    "same_modulo_enums",
]
