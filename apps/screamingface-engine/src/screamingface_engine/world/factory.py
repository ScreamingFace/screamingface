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
from pathlib import Path

import httpx

from screamingface_engine import job_env
from screamingface_engine.benchmarks import (
    EMPTY_BENCHMARKS,
    BenchmarkRegistry,
    assets_root,
)
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import (
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
from url4.streaming.protocol import CachePolicy

logger = logging.getLogger(__name__)

# CHARACTERIZATION (prd/01 AC1 — the ensemble path is byte-for-byte unchanged): the per-run
# "runner world topic=…" line was emitted on logger `screamingface_engine.runner.main` before F1
# moved its emitter into this package, and log routing keyed on that name must not change with
# the code's address. This ONE line keeps its historical logger; world-side logs that are new
# (the D8 shelf declarations below) use `logger` above.
_RUN_PATH_LOGGER = logging.getLogger("screamingface_engine.runner.main")

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

WorldFactory = Callable[[], Awaitable[World]]


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
    return node


async def build_world(
    *,
    env: Mapping[str, str],
    config: WorldConfig | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    benchmark_assets_root: Path | None = None,
    run_key: str | None = None,
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
    cache = job_env.cache_policy_from_env(env)
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
    # FEATURE (OME-1069): the world's resolved shape, logged once per run. The topic comes from
    # the run's own env (`run_key`); the trace id is appended by the run-context filter, which is
    # bound by the time the world is built. Model ids are public catalog names; `web_tools` is
    # derived from the PRESENCE of the Tavily key, never the key itself; `cache` states whether
    # the run declared a policy, not the policy's content.
    _RUN_PATH_LOGGER.info(
        "runner world topic=%s models=%d default_model=%s web_tools=%s cache=%s outbound=%s",
        run_key,
        len(section.models),
        section.default_model,
        "enabled" if world.web_tools_enabled else "disabled",
        _cache_stated(cache),
        "allowed" if section.allow_outbound else "denied",
    )
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


def _cache_stated(policy: CachePolicy) -> str:
    """Whether a run's cache policy stated anything — 'stated' or 'not-stated'.

    Its own token rather than the rendered policy: "did not declare" and "declared an
    all-unset policy" are different statements, and the world log only needs the first.
    """

    if policy.participate is not None or policy.max_age is not None:
        return "stated"
    return "not-stated"


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
    "World",
    "WorldFactory",
    "build_world",
    "deny_by_default_world",
    "register_read_side_mounts",
    "shared_world_serves",
    "world_reads_answer_seed",
]
