"""Build the node tier: validate the ladder, build the world ONCE, then the tier (FX-15).

FEATURE (unit 3, prd/03 §2.1): the node tier's composition. Every refusal here marks the
readiness failed before it propagates (AC18, FX-16), so `/readyz` names the reason.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace

import httpx

from screamingface_engine import job_env
from screamingface_engine.artifacts import ArtifactWriter, FilesystemArtifactStore
from screamingface_engine.artifacts.wiring import result_writer_from_env
from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry
from screamingface_engine.world.config import WorldConfig, config_file_digest, load_config
from screamingface_engine.world.node_tier.metrics import NodeMetrics, build_node_metrics
from screamingface_engine.world.node_tier.settings import NodeTierError, NodeTierSettings
from screamingface_engine.world.node_tier.tier import OPS_PATHS, NodeReadiness, NodeTier
from screamingface_engine.world.serving import compose_serving_world
from url4.cli._serve import ServeConfig, build_asgi_app
from url4.peer.server import Url4Node

WorldTeardown = Callable[[], Awaitable[None]]


async def build_node_tier(
    *,
    env: Mapping[str, str],
    settings: NodeTierSettings | None = None,
    config: WorldConfig | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    engine_routes: Iterable[str] | None = None,
    metrics: NodeMetrics | None = None,
    readiness: NodeReadiness | None = None,
    artifact_store: ArtifactWriter | None = None,
    artifact_signing_key: str | None = None,
    clock: Callable[[], float] | None = None,
) -> NodeTier:
    """Build the world ONCE and return a servable tier, or refuse to.

    ``config``/``client``/``tavily_client``/``benchmarks``/``metrics``/``readiness`` are injection
    seams for tests, exactly as in :func:`world.factory.build_world`. An injected
    ``artifact_store`` is trusted as given (tests); a store read from the env must not be the
    filesystem store (FX-8).

    The aigateway timeout is OVERRIDDEN here (contracts.md C3): the image's ``url4.toml`` declares
    600 s, which is right for the ensemble path and wrong for a 30 s sync budget, so the tier
    replaces it rather than inheriting it. ``allow_outbound`` is forced false (defence in depth,
    `contracts.md` §10): a direct hit never runs the DAG, so a URL-valued context stays opaque
    text, and a denying outbound layer is the backstop.

    On any settings/build/guard/store failure the readiness is marked failed before the error
    propagates, so `/readyz` (when the process is alive enough to answer) reports the reason.

    Raises:
        NodeTierError: the settings break the ladder, the world has no url4 node, the env's
            store is the filesystem store, or the signing key is empty.
    """
    resolved_settings = settings or NodeTierSettings.from_env(env)
    resolved_readiness = readiness or NodeReadiness()
    try:
        resolved_settings.validate()
        # FX-16: a store error is a build error like every other, so readiness names it.
        # WHY before the world: a refused store or key then leaves nothing built to tear down.
        store = _resolve_store(env, artifact_store)
        signing_key = _resolve_signing_key(env, artifact_signing_key)
        node, world_aclose = await _serving_node(
            env=env,
            config=_tier_config(
                config if config is not None else load_config(env), resolved_settings
            ),
            client=client,
            tavily_client=tavily_client,
            benchmarks=benchmarks,
            engine_routes=frozenset(engine_routes) if engine_routes is not None else OPS_PATHS,
        )
        tier = NodeTier(
            settings=resolved_settings,
            metrics=metrics or build_node_metrics(),
            readiness=resolved_readiness,
            node=node,
            inner=build_asgi_app(
                node,
                ServeConfig(
                    timeout=resolved_settings.request_timeout_s,
                    max_inflight=resolved_settings.max_inflight,
                ),
            ),
            world_aclose=world_aclose,
            artifact_store=store,
            signing_key=signing_key,
            clock=clock,
            config_digest=config_file_digest(env),
        )
    except Exception as exc:
        # ONE readiness-marking site for every refusal above (T4 refactor): a settings, store,
        # signing-key or world/collision failure all name their reason on `/readyz` the same way.
        resolved_readiness.fail(str(exc))
        raise
    resolved_readiness.succeed()
    return tier


async def _serving_node(
    *,
    env: Mapping[str, str],
    config: WorldConfig,
    client: httpx.AsyncClient | None,
    tavily_client: httpx.AsyncClient | None,
    benchmarks: BenchmarkRegistry,
    engine_routes: frozenset[str],
) -> tuple[Url4Node, WorldTeardown | None]:
    """Compose the guarded serving world and require it to be a url4 node (AC18).

    Raises straight through to `build_node_tier`'s one try/except, which marks readiness
    failed for this and every other refusal (T4 refactor) — this function only tears down a
    half-built world before raising, which is its own concern and not readiness's.
    """
    io, world_aclose = await compose_serving_world(
        env=env,
        engine_routes=engine_routes,
        config=config,
        client=client,
        tavily_client=tavily_client,
        benchmarks=benchmarks,
    )
    if not isinstance(io, Url4Node):
        if world_aclose is not None:
            await world_aclose()
        raise NodeTierError(
            "the declared world has no url4 node (no [aigateway] and no read-side mounts) — "
            "the node tier serves a node's ASGI surface and cannot serve an empty world"
        )
    return io, world_aclose


def _resolve_store(env: Mapping[str, str], injected: ArtifactWriter | None) -> ArtifactWriter:
    """The spill store: the injected one as given, else the env's — never the filesystem one.

    The env store is built by `result_writer_from_env`, the SAME builder the run path uses, so
    the sync tier and the Runner park into one place, and the App reads that one place.

    WHY the filesystem store is refused (FX-8, OME-929): the node pod's disk is not the App's
    disk. An artifact parked there is unfetchable from the App, so every spill would redirect
    the caller to a 404.
    """
    if injected is not None:
        return injected
    store = result_writer_from_env(env)
    if isinstance(store, FilesystemArtifactStore):
        raise NodeTierError(
            "the node tier's artifact store is the filesystem store — the node pod's disk is "
            "not the App's disk (OME-929), so a spilled response could never be fetched. Set "
            f"{job_env.ARTIFACT_STORE}=s3 for the node tier"
        )
    return store


def _resolve_signing_key(env: Mapping[str, str], injected: str | None) -> str:
    """The HMAC key the 303's Location is signed with: the injected one, else the env's.

    WHY refused when empty (FX-9): the tier always has a store, and a spill that cannot be
    signed is an unfetchable redirect. Failing at boot beats failing every large request.
    """
    key = injected if injected is not None else env.get(job_env.ARTIFACT_SIGNING_KEY, "")
    if not key:
        raise NodeTierError(
            f"the artifact signing key is empty ({job_env.ARTIFACT_SIGNING_KEY}) — the node "
            "tier cannot sign a spilled response's redirect"
        )
    return key


def _tier_config(config: WorldConfig, settings: NodeTierSettings) -> WorldConfig:
    """Apply the tier's aigateway overrides to the declared world (allow_outbound + timeout)."""
    section = config.aigateway
    if section is None:
        return config
    return replace(
        config,
        aigateway=replace(
            section,
            allow_outbound=False,
            timeout_s=settings.aigateway_timeout_s,
        ),
    )


__all__ = ["build_node_tier"]
