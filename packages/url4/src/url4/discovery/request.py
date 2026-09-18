"""Applying a caller's config to a live request — the write half of discovery.

`/.well-known/url4-config` tells a caller which items are theirs to set. This is what
makes that answer TRUE: without it the node serves a permission model and then ignores
every value sent against it, answering `200` to a request it did not honour.

A `200` means "I did what you asked". So the rule here is absolute:

    NEVER answer 200 to a request carrying config the node did not apply.

Either the values are applied, or the request is refused with a problem that says why.
Silently dropping them is the one outcome that is not allowed, because the caller cannot
tell it apart from success — their eval run is then wrong and nothing told them.

WHICH SCHEMA judges the values is decided by the expression: config is per-ENDPOINT, so
the node reads the routes the expression addresses and matches them against the mount
table. Exactly one mount is the case it can answer; zero and several are refused rather
than guessed at, because applying an endpoint's config to a different endpoint is worse
than declining.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from url4.core.parser import build
from url4.discovery.carrier import coerce, from_headers
from url4.discovery.problem import config_rejected
from url4.discovery.scope import USER, Code, Violation, enforce
from url4.discovery.wellknown import Mount


@dataclass(frozen=True)
class Applied:
    """The outcome of reading a caller's config for one request.

    ``values`` is what may be forwarded; ``problem`` is the RFC 9457 body to return
    instead. Exactly one is meaningful — a caller either gets their values applied or
    gets told why not.
    """

    values: dict[str, Any]
    problem: dict | None = None

    @property
    def rejected(self) -> bool:
        return self.problem is not None


def addressed_routes(expression: str) -> frozenset[str]:
    """Every local route the expression addresses, in either form.

    Two AST shapes reach a route and BOTH count:

    * ``RelExpr.path`` — `/claude-fast(ctx)!'intent'`, an endpoint CALL.
    * ``RelUrl.value`` — `(/claude-fast)!'intent'`, the same route read as a SOURCE.

    Collecting only the call form would let a caller address a mount the source way and
    have their config silently dropped, which is precisely the outcome this module
    exists to prevent.

    A parse failure yields the empty set rather than raising: the expression is about to
    be parsed again by the node, which owns the grammar error and reports it far better
    than this layer could.
    """
    try:
        return frozenset(_collect_paths(build(expression)))
    except Exception:  # noqa: BLE001 - the node reports grammar errors, not this layer
        return frozenset()


def _collect_paths(node: Any, seen: set[int] | None = None) -> list[str]:
    """Walk the AST generically, collecting `path` off anything that addresses a route.

    Generic rather than a per-type visitor because the AST has thirteen node types and a
    fourteenth would otherwise be silently skipped — and a skipped node type means a
    route the node does not know it is about to call.
    """
    seen = set() if seen is None else seen
    found: list[str] = []
    if id(node) in seen:
        return found
    seen.add(id(node))

    if isinstance(node, (list, tuple)):
        children: tuple[Any, ...] = tuple(node)
    elif is_dataclass(node) and not isinstance(node, type):
        found.extend(_route_of(node))
        children = tuple(getattr(node, field.name) for field in fields(node))
    else:
        children = ()

    for child in children:
        found.extend(_collect_paths(child, seen))
    return found


def _route_of(node: Any) -> list[str]:
    """This node's own local route, if it addresses one.

    `RemoteExpr` also carries `path`, but it addresses ANOTHER node's route —
    `authority` is what distinguishes it, and its config is that node's business.
    """
    if getattr(node, "authority", None):
        return []
    return [
        candidate
        for attribute in ("path", "value")
        if isinstance(candidate := getattr(node, attribute, None), str)
        and candidate.startswith("/")
    ]


def read_request_config(
    headers: Iterable[tuple[bytes, bytes]],
    expression: str,
    mounts: Sequence[Mount],
    *,
    instance: str | None = None,
) -> Applied:
    """Read, judge, and either apply or refuse a caller's config for one request.

    ``mounts`` are the mounts as THIS caller sees them — each carrying the schema its
    endpoint served for them, so the enum is already narrowed by their entitlements.
    """
    raw = from_headers(headers)
    if not raw:
        return Applied(values={})

    schema, why = _judging_schema(expression, mounts)
    if schema is None:
        return Applied(values={}, problem=config_rejected([why], instance=instance))

    typed, _unparseable = coerce(raw, schema)
    violations = enforce(typed, schema, actor=USER)
    problem = config_rejected(violations, instance=instance) if violations else None
    return Applied(values={} if violations else typed, problem=problem)


def _judging_schema(
    expression: str, mounts: Sequence[Mount]
) -> tuple[Mapping[str, Any] | None, Violation]:
    """The one schema these values are judged against, or the reason there isn't one.

    The second element is only meaningful when the first is None; it is built either way
    so the caller has one shape to handle.
    """
    routes = addressed_routes(expression)
    by_path = {mount.path: mount for mount in mounts}
    addressed = sorted(routes & set(by_path))
    mount = by_path[addressed[0]] if len(addressed) == 1 else None

    # Each case is refused rather than guessed at. Applying one endpoint's config to
    # another is a silent wrong answer, which is the failure this module exists to stop.
    reasons = (
        (
            not addressed,
            "this request carries config but addresses no mounted endpoint, so there is "
            "no schema to judge it against — remove the URL4-Config-* headers, or address "
            f"one of {sorted(by_path)}",
        ),
        (
            len(addressed) > 1,
            f"this request addresses {addressed} and config is per-endpoint, so which one "
            "these values belong to is ambiguous — send one endpoint per request",
        ),
        (
            mount is not None and mount.served_schema is None,
            # `mount.path` rather than `addressed[0]`: every arm of this tuple is built
            # eagerly, so indexing a list that may be empty raises before the guard that
            # would have protected it is ever consulted.
            f"mount {(mount.path if mount else '')!r} is unavailable — the node holds no "
            "schema for it, so it cannot tell whether these values are yours to set",
        ),
    )
    hit = next((detail for bad, detail in reasons if bad), None)
    schema = mount.served_schema if hit is None and mount is not None else None
    return schema, Violation(Code.UNKNOWN_ITEM, "", hit or "")


__all__ = ["Applied", "addressed_routes", "read_request_config"]
