"""F4 (prd/02): fail startup when an engine route shadows a url4 mount.

Under D3 the node keeps url4's default ``eval_path="/v1"`` and collisions between an ENGINE
literal route and a url4 mount are resolved by FastAPI route precedence. Precedence is SILENT:
an engine route registered before the node's ASGI mount wins, and the only symptom is a mount
that stops answering — a 404 on a process that looks perfectly healthy. url4's own
``_check_routable`` refuses duplicates WITHIN the node; it cannot see the engine's FastAPI route
table. This module closes that engine-versus-node gap by collecting both sides and failing
startup, naming both the mount and the shadowing route (AC5).

The same check pins the case D3 depends on. ``eval_path="/v1"`` must survive the engine's
``/v1/models``, ``/v1/benchmarks`` and ``/v1/connections``: each is a strictly LONGER literal, so
it wins only its own exact path while the eval path keeps the rest. A hypothetical engine route
at exactly ``/v1`` would eat the eval path entirely and must fail (AC6). This is the difference
between "precedence works" and "precedence silently ate the eval path".

# INVARIANT: :func:`compose_serving_world` is the ONE place a world is composed for serving.
# `serve --local` mounts the node inside the App; the node tier serves it directly. Both call the
# helper, so their mount sets and this guard cannot diverge. The run mode keeps calling
# `world.factory.build_world` directly: it does not serve, so it has no engine route set to
# check against.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
from starlette._utils import get_route_path
from starlette.applications import Starlette
from starlette.datastructures import URLPath
from starlette.routing import BaseRoute, Match, Mount, NoMatchFound, compile_path
from starlette.types import Receive, Scope, Send

from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry
from screamingface_engine.benchmarks.registry import served_routes
from screamingface_engine.world.config import DEFAULT_EVAL_PATH, WorldConfig, WorldConfigError
from screamingface_engine.world.factory import World, build_world
from screamingface_engine.world.wire import AsgiApp
from url4.peer.server import Url4Node

logger = logging.getLogger(__name__)


class MountCollisionError(WorldConfigError):
    """An engine route shadows a node mount or the node's eval path — startup must fail (F4)."""


# The pattern `_iter_route_paths` yields for a Starlette `Mount`'s subtree (FX-50). Its parameter
# name is the engine's own, so `_mount_message` can tell a mounted sub-app from a real engine
# route that happens to end in a `{name:path}` parameter (B3 review R9).
_MOUNT_SUBTREE = "/{mounted_subapp_path:path}"


def engine_route_paths(app: object) -> frozenset[str]:
    """Every path the FastAPI app registers, flattened.

    WHY derive rather than list every route name here: a hand-maintained list of ``/v1/models``,
    ``/token``, … rots the day a router is added — and a new router is exactly the day this
    guard has to fire. The walker follows FastAPI 0.141's ``_IncludedRouter`` wrappers (an
    included router is no longer flattened into ``app.routes``) so ``include_router`` is seen
    with or without a prefix, and it also collects WebSocket routes, which the app's own
    effective-route view omits.
    """
    return frozenset(_iter_route_paths(getattr(app, "routes", ())))


def _iter_route_paths(routes: Iterable[object]) -> Iterator[str]:
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            yield path
            if isinstance(route, Mount):
                # FX-50 (U2-1): a Mount is a FULL match for its own path AND every path under
                # `path + "/"` (`Mount.path_regex` is compiled from exactly this pattern — see
                # `Mount.__init__`). A literal-only comparison of `route.path` would miss the
                # whole subtree a Mount actually serves (`/diagrams/foo` under `/diagrams`), so
                # this yields the SAME pattern Starlette itself matches with, and `_route_matches`
                # (below) needs no extra branch to honor it.
                yield f"{path}{_MOUNT_SUBTREE}"
            continue
        original = getattr(route, "original_router", None)
        if original is None:
            continue
        prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
        for child in _iter_route_paths(getattr(original, "routes", ())):
            yield f"{prefix}{child}"


def node_mount_paths(node: Any) -> frozenset[str]:
    """Every URL path the node serves directly: its endpoints and its data routes.

    Holdings and identity shelves are addressed as ``@``/``@name``, never as URL paths, so they
    cannot collide with a FastAPI route and are deliberately absent. The paths come from
    ``benchmarks.registry.served_routes`` — the ONE accessor for endpoints plus data routes
    (FX-55, B3 review R8), which the benchmark install reads too.

    FX-56: ``isinstance`` rather than duck typing. A non-``Url4Node`` layer (``StaticIOLayer``,
    ``deny_by_default_world``) has no mounts to protect by construction, and checking the type
    directly says so instead of relying on an object happening to expose the same method names.
    """
    if not isinstance(node, Url4Node):
        return frozenset()
    return served_routes(node)


def node_eval_path(node: Any, *, default: str = DEFAULT_EVAL_PATH) -> str:
    """The node's eval path, or ``default`` when the layer is not a ``Url4Node``.

    A non-node layer (``StaticIOLayer``, ``deny_by_default_world``) claims no eval path.
    :func:`check_mount_collisions` therefore never calls this for one (FX-56); the default is
    for callers such as local mode, which routes the eval path only once a node exists.

    FX-56: ``isinstance`` rather than duck typing, for the same reason as ``node_mount_paths``.
    """
    if not isinstance(node, Url4Node):
        return default
    # WHY the private `_eval_path` read: `Url4Node` exposes no public eval-path accessor, and
    # widening url4's API is outside this landing's boundary.
    return str(node._eval_path)


def check_mount_collisions(node: Any, engine_routes: Iterable[str]) -> None:
    """Fail when an engine route shadows a node mount or the node's eval path (F4, AC5, AC6).

    Two checks, both loud:

    1. Every mount path an engine route matches EXACTLY. A literal ``/token`` route and a
       ``/token`` data mount collide; a parameterised ``/artifacts/{artifact_id}`` route also
       shadows a mount at ``/artifacts/foo``, which a literal-only comparison would miss.
    2. The eval path. Because the router resolves literal routes first, an engine route at
       exactly ``/v1`` removes the bare eval path entirely. Longer literals under ``/v1/...`` do
       NOT collide — that is the longer-literal-wins rule AC6 pins, and the reason D3 works.

    WHY fail and not warn: a shadowed mount is invisible at runtime. Startup failure is the only
    loud signal, and it is cheap because nothing has been served yet (00-overview D3).
    """
    routes = tuple(engine_routes)
    for mount in sorted(node_mount_paths(node)):
        for route in routes:
            if _route_matches(route, mount):
                raise MountCollisionError(_mount_message(route, mount))
    if not isinstance(node, Url4Node):
        # FX-56: a non-node layer (StaticIOLayer) has no eval path to protect — `node_eval_path`
        # would answer DEFAULT_EVAL_PATH for it, and checking that default against the engine's
        # routes would be a check against a path this layer never actually claims.
        return
    eval_path = node_eval_path(node)
    for route in routes:
        if _route_matches(route, eval_path):
            raise MountCollisionError(
                f"engine route {route!r} shadows the node eval path {eval_path!r} — every bare "
                f"{eval_path!r} request would be answered by the engine route instead of the "
                "node. Rename the engine route or change the node's eval_path (prd/02 F4, AC6)."
            )
    _warn_holdings_shadowed_by_engine_routes(node, routes, eval_path)


def _route_matches(route_path: str, candidate: str) -> bool:
    """Whether a FastAPI route pattern matches ``candidate`` EXACTLY.

    WHY starlette's own compiler: a hand-rolled segment comparison would disagree with the
    router the day a path converter appears (``{artifact_id:path}``), and the guard would then
    pass a mount the router silently eats. One matcher owns the semantics, so the guard and the
    router cannot drift (the same reason D3 delegates precedence to FastAPI at all).

    FX-56: no ``except ValueError`` fallback. Every ``route_path`` this function ever receives
    comes from a route Starlette already registered on the real App (`engine_route_paths`) —
    Starlette itself would have failed AT REGISTRATION on a pattern ``compile_path`` cannot
    parse, so a route reaching here has already been proven compilable; a fallback for that case
    was dead code no test could reach honestly.
    """
    regex, _format, _convertors = compile_path(route_path)
    return regex.match(candidate) is not None


def _mount_message(route: str, mount: str) -> str:
    if route.endswith(_MOUNT_SUBTREE):
        # R9: name the route the operator wrote (`/diagrams`), not the synthetic subtree pattern.
        mounted = route.removesuffix(_MOUNT_SUBTREE)
        return (
            f"engine route {mounted!r} (a mounted sub-app, which answers every method on every "
            f"path under it) shadows the node mount {mount!r} — every request for the mount is "
            "answered by the sub-app instead, because FastAPI resolves engine routes before the "
            "node's mount. Rename the mount or the engine route; route precedence is silent "
            "(prd/02 F4, AC5)."
        )
    return (
        f"engine route {route!r} shadows the node mount {mount!r} — a request for one of the "
        "engine route's own methods is answered by the engine route instead of the mount, "
        "because FastAPI resolves engine literal routes before the node's mount. Rename the "
        "mount or the engine route; route precedence is silent (prd/02 F4, AC5)."
    )


def _warn_holdings_shadowed_by_engine_routes(
    node: Url4Node, routes: tuple[str, ...], eval_path: str
) -> None:
    """Warn — never fail — when a ``[holdings]`` collection name equals an engine literal
    route's last segment directly under the eval path (FX-57, U2-11).

    Example: collection ``models`` versus the real engine route ``/v1/models``. The self-holdings
    qualifier form ``/v1/models?q=(@)`` is then answered by the engine route instead of resolving
    ``@models`` on this node. WHY warn and not raise: a mount collision takes a declared path
    away from the node for every request the engine route answers, while the shadow here is
    narrow — one query form under one literal path — and ``@models`` still resolves correctly
    from any OTHER expression, so it does not justify failing startup the way
    :func:`check_mount_collisions`'s other checks do.
    """
    collections = _holdings_collection_names(node)
    if not collections:
        return
    prefix = f"{eval_path}/"
    for route in routes:
        if not route.startswith(prefix):
            continue
        segment = route[len(prefix) :]
        if not segment or "/" in segment or "{" in segment:
            continue  # not a literal, single-segment route under the eval path
        if segment in collections:
            logger.warning(
                "holdings collection %r collides with the engine literal route %r under the "
                "eval path %r — %r is answered by the engine route, not the %r shelf "
                "(prd/02 U2-11)",
                segment,
                route,
                eval_path,
                route,
                segment,
            )


def _holdings_collection_names(node: Url4Node) -> frozenset[str]:
    """Every NAMED ``[holdings]`` collection on ``node`` (the default shelf, keyed ``None``, is
    excluded — it names no path segment to collide with).

    WHY read privately: like the data table (``benchmarks.registry.data_routes``), ``Url4Node``
    publishes no accessor for its holdings registry — widening the engine's API is outside this
    fix's scope. ``node`` is a known ``Url4Node``, so the attribute is read directly.
    """
    return frozenset(name for name in node._self_holdings if name is not None)


async def compose_serving_world(
    *,
    env: Mapping[str, str],
    engine_routes: Iterable[str],
    config: WorldConfig | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    benchmark_assets_root: Path | None = None,
    run_key: str | None = None,
) -> World:
    """Compose a world FOR SERVING and refuse a mount an engine route would shadow (F4).

    The single composition helper both deployment shapes call (see the module INVARIANT). It is
    a thin wrapper over :func:`~screamingface_engine.world.factory.build_world` plus the guard;
    ``build_world``'s own semantics and teardown are unchanged.

    A collision tears the world down before the error propagates, matching F3's mount
    registration: a half-built world must not survive an error, and the caller must not have to
    remember to close it.
    """
    world = await build_world(
        env=env,
        config=config,
        client=client,
        tavily_client=tavily_client,
        benchmarks=benchmarks,
        benchmark_assets_root=benchmark_assets_root,
        run_key=run_key,
    )
    _io, aclose = world
    try:
        check_mount_collisions(_io, engine_routes)
    except MountCollisionError:
        if aclose is not None:
            await aclose()
        raise
    return world


class NodeMountRoute(BaseRoute):
    """The node's surface on the App: a route that matches ONLY the paths the node serves.

    FEATURE (unit 3, 04-review-fixes §2.3): the deployed App forwards its declared mounts to the
    node tier, and ``serve --local`` serves them in-process. Both install THIS route, last.

    WHY not ``Mount("/")``: a catch-all mount is a FULL match for every path, so it changed the
    answer on existing engine routes — a wrong method on ``/token`` became url4's 404 instead of
    the engine's 405, and ``/healthz/`` was never redirected. A route that matches only known
    paths leaves Starlette's normal answers (405, the trailing-slash 307, the engine's 404) in
    place for everything else, and an unknown path never reaches the node.

    INVARIANT: the match is on the PATH, never the method. Any method on a known path is a FULL
    match, so the node's own 405 answers a wrong method on a mount (AC14).

    WHY ``paths`` is a callable, not a set: the App derives its mount set in a startup hook, after
    this route is installed, so the route reads the set at match time.
    """

    def __init__(self, app: AsgiApp, *, paths: Callable[[], frozenset[str]], name: str) -> None:
        self.app = app
        self.name = name
        self._paths = paths

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        # WHY `get_route_path` and not `scope["path"]`: behind a `root_path` the router matches
        # the path minus that prefix, as every Starlette route does. It is private to Starlette,
        # but it is the function the router itself calls, so the two cannot disagree.
        if scope["type"] == "http" and get_route_path(scope) in self._paths():
            return Match.FULL, {"endpoint": self.app}
        return Match.NONE, {}

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        # The node's paths are data, not named routes: nothing may build a URL to one by name.
        raise NoMatchFound(name, path_params)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def install_node_route(app: Starlette, route: NodeMountRoute) -> None:
    """Append the node route to ``app`` and assert that it is the last and only one (D3).

    The ONE install function for both shapes (FX-32): the deployed App's forwarder and local
    mode's in-process node both come through here, so the ordering check cannot be skipped by one.
    """
    app.router.routes.append(route)
    assert_node_route_last(app, route)


def assert_node_route_last(app: Starlette, route: NodeMountRoute) -> None:
    """Raise unless ``route`` is the App's LAST route and its ONLY node route.

    WHY last: the router tries routes in order, so every engine route is tried first (D3) and a
    path that is both an engine route and a mount goes to the engine — which F4's guard then
    refuses at startup, loudly. WHY one: a second node route would split the node's surface
    between two path sets. WHY an assertion: a comment cannot stop a future ``include_router``
    from landing below the install call; this check can.
    """
    routes = list(app.router.routes)
    if not routes or routes[-1] is not route:
        raise AssertionError(
            "the node route must be the LAST route: register it after every engine route and "
            "router (prd/03 D3; world.serving.install_node_route)."
        )
    node_routes = [candidate for candidate in routes if isinstance(candidate, NodeMountRoute)]
    if node_routes != [route]:
        raise AssertionError(
            "exactly ONE node route may exist: a second would shadow the node or the engine "
            "depending on registration order (prd/03 D3)."
        )


__all__ = [
    "MountCollisionError",
    "NodeMountRoute",
    "assert_node_route_last",
    "check_mount_collisions",
    "compose_serving_world",
    "engine_route_paths",
    "install_node_route",
    "node_eval_path",
    "node_mount_paths",
]
