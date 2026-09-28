"""Build the shared world (prd/01 F1): config -> `Url4Node` -> installed endpoints.

FEATURE (F1, prd/01): this is the `_world()` factory body that used to be a closure inside
``runner.main.build_executor``. It moved here because building a world is what BOTH halves do —
the run mode builds one per Job (still, until unit 3), and the control plane (unit 3) will build
one per process — so the logic cannot live in the run mode's package.

WHY the world is built LAZILY by its callers: a bad config or an unreachable gateway must surface
INSIDE the run (a Terminated frame on the topic) rather than taking down the scheduling caller
before the stream exists. This module therefore exposes a builder, not a built world; the run
mode wraps it in ``Url4Executor``'s lazy ``world_factory``. It carries NO caller state (F2): the
connector reads identity, profile, cache policy and answer seed from the `request_scope` ContextVar,
so one world serves many callers.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

import httpx

from screamingface_engine import job_env
from screamingface_engine.benchmarks import (
    EMPTY_BENCHMARKS,
    BenchmarkRegistry,
    assets_root,
)
from screamingface_engine.benchmarks.registry import served_routes
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    extra_model_ids,
    load_config,
    routes_for,
    shelf_label,
)
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.corrective import install_corrective_runtime
from url4.cli._serve import make_data_provider, make_identity_handler, make_shelf_handler
from url4.io.layer import IOLayer
from url4.io.static import StaticIOLayer
from url4.peer.server import Url4Node

logger = logging.getLogger(__name__)

# AIDEV-NOTE (FX-68): the per-run "runner world topic=…" line is NOT written here. It states the
# RUN's cache policy, and a world carries no caller state (F2), so the run producer
# (`runner.main`) writes it, once per run — on a per-run world and on the shared node alike.

READ_SIDE_TIMEOUT_S = 120.0
"""Provider timeout passed to url4's read-side handler builders.

Kept equal to url4 serve's own default so a shelf behaves the same on either tier. It is inert
for ``value`` and ``file`` providers (neither reads it), and ``command`` providers are refused in
EVERY read-side section at config load (R12), so no accepted declaration currently reaches it.
The constant stays because the handler builders require it and dropping it would be a refactor
beyond the exec-surface fix.
"""

World = tuple[IOLayer, Callable[[], Awaitable[None]] | None]
"""A resolved world: its io layer plus the teardown that owns whatever it allocated.

Defined HERE, in the shared world, rather than in `runner.executor`: the engine-importing half is
the world builder, and the run mode's executor types its factory against this without owning the
definition. `tests/unit/test_url4_executor.py` pins which modules may import the url4 engine.
"""


@dataclass(frozen=True, slots=True)
class SharedWorld:
    """A local-mode shared world: its io layer, plus the ``[aigateway]`` section it was built
    from (B6 review round 2, item 2).

    ONE object rather than two independent optional providers (``io_provider`` and a second
    ``io_config_provider``): a caller supplying the io half without the section half used to
    compile and run fine, silently dropping the run's "runner world" log line (item 1) with no
    signal anywhere that anything was missing. Bundling both into one value a provider returns
    together makes that omission a construction error instead of a silent one.

    ``section`` is ``None`` for a shared world with no ``[aigateway]`` table (a bare read-side
    node, or the deny-by-default layer) — the same shape that writes no world line on `main`.
    """

    io: IOLayer
    section: AigatewaySection | None


WorldFactory = Callable[[], Awaitable[World]]

_DIRECT_MOUNTS: WeakKeyDictionary[Url4Node, frozenset[str]] = WeakKeyDictionary()
"""The DIRECT-mount route set `build_world` captured for a node, keyed by the node itself.

WHY a side table and not an attribute on the node (as this used to be): `local.py` reads it back
through `direct_mount_paths` below and may not import the url4 engine
(test_only_engine_extensions_import_url4), so it cannot spell `Url4Node` to type an attribute
access either — an engine-owned table, read through an engine-owned accessor, is what keeps the
node's own type unwidened by a caller that must not know its shape.
"""


def direct_mount_paths(node: Any) -> frozenset[str]:
    """The DIRECT-mount route set for ``node``: model + data mounts, WITHOUT benchmark/candidate/
    corrective/judge endpoints.

    `build_world` records this right before Benchmarks install, so `local.py`'s direct-mount set
    reads it back here instead of re-deriving "final routes minus benchmark routes" through a
    second scratch-node build (see `build_world`'s own comment for why). A node with no recorded
    entry — a bare read-side node, which never has Benchmarks installed on it — falls back to
    `served_routes`, its final served-route set already.

    WHY `isinstance` rather than duck typing: a non-`Url4Node` layer (`StaticIOLayer`, the
    deny-by-default world) has no mounts to report by construction, the same reasoning
    `world.serving.node_mount_paths` uses (FX-56).
    """
    if not isinstance(node, Url4Node):
        return frozenset()
    return _DIRECT_MOUNTS.get(node, served_routes(node))


def deny_by_default_world() -> IOLayer:
    """A world that resolves nothing — the shape of a Job with no declared `[aigateway]` table."""

    return StaticIOLayer()


def _bare_read_side_world(resolved: WorldConfig) -> Url4Node:
    """A read-side-only declaration becomes a bare node — not a deny-by-default layer.

    WHY ``outbound=StaticIOLayer()`` (FX-51): a read-side-only declaration has no ``[aigateway]``
    table, so nothing on this node should ever reach an absolute URL. Leaving ``outbound``
    unset would make ``Url4Node`` create and OWN an httpx adapter lazily — an ``https://`` fetch
    would then silently succeed, exactly the outbound access the operator never declared.
    ``StaticIOLayer`` denies every absolute target instead, the same deny-by-default posture
    :func:`deny_by_default_world` gives a world with no read-side mounts either.

    WHY the same ``ValueError`` → ``WorldConfigError`` translation as the aigateway branch in
    :func:`build_world`: a registration failure must surface as ``WorldConfigError`` whichever
    branch declared the mounts.
    """
    node = Url4Node("world", outbound=StaticIOLayer())
    try:
        register_read_side_mounts(node, resolved)
    except ValueError as exc:
        raise WorldConfigError(f"cannot register the declared read-side mounts: {exc}") from exc
    # No entry in `_DIRECT_MOUNTS` for this node: `direct_mount_paths`'s fallback to
    # `served_routes` is exactly right here, since no Benchmark is ever installed on a bare
    # read-side node (`build_world` refuses one when `[aigateway]` is undeclared) — this IS the
    # node's final served-route set already.
    return node


async def build_world(
    *,
    env: Mapping[str, str],
    config: WorldConfig | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    benchmark_assets_root: Path | None = None,
) -> World:
    """Build the declared world and install every endpoint it needs.

    ``config`` is an injection seam for tests; production passes ``None`` and the Job's own env is
    parsed here. ``client`` and ``tavily_client`` are test-only injection seams for the same
    reason: production leaves them ``None`` and ``build_aigateway_world`` constructs its own
    ``httpx.AsyncClient``(s).

    Raises:
        WorldConfigError: a malformed/undeclared config, Benchmarks installed without a
            declared aigateway model world, or a declared route a benchmark endpoint collides
            with.
    """

    # `include_extra_models`: the Runner boot is the ONE parse that reads the Job-scoped
    # URL4_CLOUD_EXTRA_MODELS overlay (review F3) — this env IS the Job's own, written by the
    # App at schedule time.
    resolved = config if config is not None else load_config(env, include_extra_models=True)
    section = resolved.aigateway
    if section is None:
        if len(benchmarks):
            raise WorldConfigError("installed Benchmarks require a declared aigateway model world")
        if not _has_read_side(resolved):
            # WHY: a world with no [aigateway] table and no read-side mounts is a legitimate empty
            # world; the node itself denies everything undeclared.
            return deny_by_default_world(), None
        # WHY a bare node: a [data]/[holdings]/[identities]-only declaration must still become a
        # mount (F3, prd/02 AC1). Returning the deny-by-default layer here would drop the operator's
        # declaration in silence — the exact failure AC3 rejects for command providers.
        # WHY `node.aclose` and not `None` (FX-51): it keeps this world's teardown the same shape
        # as every other world this factory returns. It closes only an adapter url4 OWNS, so with
        # the injected `StaticIOLayer` it has nothing to close: the `StaticIOLayer` is what
        # removes the outbound path (and the owned adapter nobody closed), not the teardown.
        node = _bare_read_side_world(resolved)
        return node, node.aclose
    # WHY: no credential check here; aigateway runs `cloudflare_headers` when deployed and
    # `disabled` locally, and NEITHER mode reads `Authorization` — so there is no token to demand.
    # Identity is forwarded when present and simply absent locally, where every caller is
    # anonymous.
    world = await build_aigateway_world(
        AigatewayConfig(
            base_url=section.base_url,
            default_model=section.default_model,
            models=section.models,
            allow_outbound=section.allow_outbound,
            timeout_s=section.timeout_s,
            web_tool_max_iterations=section.web_tool_max_iterations,
        ),
        client=client,
        tavily_api_key=env.get(job_env.TAVILY_API_KEY),
        tavily_client=tavily_client,
    )
    # F3 (prd/02): the read-side mounts register on the SAME node that serves model routes, before
    # any benchmark endpoint, so a declared path is addressable exactly where a model route is. A
    # registration failure closes the world first — a half-built world must not survive an error.
    try:
        register_read_side_mounts(world.node, resolved)
    except ValueError as exc:
        await world.aclose()
        raise WorldConfigError(f"cannot register the declared read-side mounts: {exc}") from exc
    # Capture the DIRECT-mount route set NOW — model + data mounts, before any Benchmark or the
    # shared candidate/corrective adapters (below) ever exist on this node. `local.py`'s
    # direct-mount set reads this back through `direct_mount_paths` (an engine-owned side table,
    # not an attribute on the node: `build_world`'s return is the shared `World` tuple both the
    # run mode and `world.serving.compose_serving_world` unpack, so widening it here would ripple
    # into both, and `local.py` may not import `Url4Node` to type an attribute access either)
    # instead of re-deriving "final routes minus benchmark routes" through a second scratch-node
    # build.
    _DIRECT_MOUNTS[world.node] = served_routes(world.node)
    if len(benchmarks):
        # WHY: installation can fail through any concrete Benchmark adapter. AsyncExitStack
        # guarantees the already-open model world closes without a catch-all exception clause.
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(world.aclose)
            try:
                install_candidate_invocation(world.node)
                # The corrective loop's generic gate/select/answer endpoints are engine
                # capability, not benchmark surface — installed once beside the candidate
                # invocation for every world that runs benchmarks.
                install_corrective_runtime(world.node)
                benchmarks.install(
                    world.node,
                    assets_root=(
                        benchmark_assets_root
                        if benchmark_assets_root is not None
                        else assets_root(env)
                    ),
                )
            except ValueError as exc:
                # WHY (B3 review R2): url4 refuses a duplicate route with a raw `ValueError` —
                # e.g. a `[data]` mount at `/benchmarks/candidate`. The same translation as the
                # read-side registration above, so a caller catches one type. The exit stack
                # still closes the world as the error leaves.
                raise WorldConfigError(f"cannot install the benchmark endpoints: {exc}") from exc
            cleanup.pop_all()
    return world.node, world.aclose


def shared_world_serves(io: IOLayer, env: Mapping[str, str]) -> bool:
    """Whether the shared world routes every model the run's admitted overlay names (FX-30).

    FEATURE (OME-880, contracts.md C8): a model the gateway admits AFTER local startup reaches a
    run only through ``URL4_CLOUD_EXTRA_MODELS``, and the shared node was built before it existed.
    ``False`` tells the caller to build a per-run world, as every run did before the shared node.

    WHY ``routes_for`` over ``ModelSpec`` ids: it is the encoding ``build_aigateway_world``
    registers routes with, so this check and the node cannot disagree about a route's path.

    WHY a malformed overlay is ``False`` and not a raise: the per-run world parses it again and
    refuses it with its own loud ``WorldConfigError`` — the one error this overlay has always had.
    """
    try:
        ids = extra_model_ids(env)
    except WorldConfigError:
        return False
    wanted = routes_for(tuple(ModelSpec(id=model_id) for model_id in ids))
    served = frozenset(io.processor_routes()) if isinstance(io, Url4Node) else frozenset()
    return wanted.keys() <= served


def world_reads_answer_seed(io: IOLayer) -> bool:
    """Whether a built world has a model call that reads the run's answer seed (FX-40).

    The run-mode twin of "``[aigateway]`` is declared": only the connector's model endpoints read
    the seed, and a world has them exactly when it is a node with processor routes. A bare
    read-side node has data routes only, and the deny-by-default layer is not a node at all.
    """
    return isinstance(io, Url4Node) and bool(io.processor_routes())


def _has_read_side(config: WorldConfig) -> bool:
    return bool(config.data or config.holdings or config.identities)


def register_read_side_mounts(node: Url4Node, config: WorldConfig) -> None:
    """Register the declared `[data]`/`[holdings]`/`[identities]` mounts on ``node`` (F3).

    WHY delegation: the provider semantics — value vs file vs command, the ``default`` shelf
    normalisation, the exact-then-default collection fallback — are url4's, taken verbatim from
    its own handler builders. A local re-implementation would let the engine and `url4 serve`
    disagree about the same file, and no test could tell that they had.

    INVARIANT (D8): every shelf declared here is readable by EVERY caller of the sync surface.
    `_log_declared_shelves` is the only thing that says so at boot, and it is called LAST so a new
    mount kind added here cannot skip the warning.
    """
    for path, spec in config.data.items():
        node.data(path, make_data_provider(spec, READ_SIDE_TIMEOUT_S), media_type=spec.media_type)
    for collection, spec in config.holdings.items():
        node.holdings(collection)(make_shelf_handler(spec, READ_SIDE_TIMEOUT_S))
    for name, shelves in config.identities.items():
        node.identity(name)(make_identity_handler(name, shelves, READ_SIDE_TIMEOUT_S))
    _log_declared_shelves(config)


def _log_declared_shelves(config: WorldConfig) -> None:
    """Say, at INFO, which shelves are global — the one control D8's shared visibility gets.

    WHY at INFO and not DEBUG: under D8 a shelf is readable by every sync caller, so an operator
    who put per-team content in `[holdings]` has no isolation and must see that at boot. The
    wording is literal ("EVERY caller of the sync surface") so it cannot be read as a caveat.
    """
    for collection in config.holdings:
        logger.info(
            "world holdings shelf %s declared — shelves are readable by EVERY caller of the "
            "sync surface",
            shelf_label(collection),
        )
    for name, shelves in config.identities.items():
        for collection in shelves:
            logger.info(
                "world identity shelf %s %s declared — shelves are readable by EVERY caller "
                "of the sync surface",
                name,
                shelf_label(collection),
            )


__all__ = [
    "READ_SIDE_TIMEOUT_S",
    "SharedWorld",
    "World",
    "WorldFactory",
    "build_world",
    "deny_by_default_world",
    "direct_mount_paths",
    "register_read_side_mounts",
    "shared_world_serves",
    "world_reads_answer_seed",
]
