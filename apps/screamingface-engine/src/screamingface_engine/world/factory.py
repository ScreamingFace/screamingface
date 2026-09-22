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
from screamingface_engine.world.config import WorldConfig, WorldConfigError, load_config
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.corrective import install_corrective_runtime
from url4.io.layer import IOLayer
from url4.io.static import StaticIOLayer
from url4.streaming.protocol import CachePolicy

logger = logging.getLogger(__name__)

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
        WorldConfigError: a malformed/undeclared config, or Benchmarks installed without a
            declared aigateway model world.
    """

    # `include_extra_models`: the Runner boot is the ONE parse that reads the Job-scoped
    # URL4_CLOUD_EXTRA_MODELS overlay (review F3) — this env IS the Job's own, written by the
    # App at schedule time.
    resolved = config if config is not None else load_config(env, include_extra_models=True)
    section = resolved.aigateway
    if section is None:
        if len(benchmarks):
            raise WorldConfigError("installed Benchmarks require a declared aigateway model world")
        # WHY: a world with no [aigateway] table is a legitimate empty world; the node itself
        # denies everything undeclared.
        return deny_by_default_world(), None
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
    if len(benchmarks):
        # WHY: installation can fail through any concrete Benchmark adapter. AsyncExitStack
        # guarantees the already-open model world closes without a catch-all exception clause.
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(world.aclose)
            install_candidate_invocation(world.node)
            # The corrective loop's generic gate/select/answer endpoints are engine capability,
            # not benchmark surface — installed once beside the candidate invocation for every
            # world that runs benchmarks.
            install_corrective_runtime(world.node)
            benchmarks.install(
                world.node,
                assets_root=(
                    benchmark_assets_root if benchmark_assets_root is not None else assets_root(env)
                ),
            )
            cleanup.pop_all()
    # FEATURE (OME-1069): the world's resolved shape, logged once per run. The topic comes from
    # the run's own env (`run_key`); the trace id is appended by the run-context filter, which is
    # bound by the time the world is built. Model ids are public catalog names; `web_tools` is
    # derived from the PRESENCE of the Tavily key, never the key itself; `cache` states whether
    # the run declared a policy, not the policy's content.
    logger.info(
        "runner world topic=%s models=%d default_model=%s web_tools=%s cache=%s outbound=%s",
        run_key,
        len(section.models),
        section.default_model,
        "enabled" if world.web_tools_enabled else "disabled",
        _cache_stated(cache),
        "allowed" if section.allow_outbound else "denied",
    )
    return world.node, world.aclose


def _cache_stated(policy: CachePolicy) -> str:
    """Whether a run's cache policy stated anything — 'stated' or 'not-stated'.

    Its own token rather than the rendered policy: "did not declare" and "declared an
    all-unset policy" are different statements, and the world log only needs the first.
    """

    if policy.participate is not None or policy.max_age is not None:
        return "stated"
    return "not-stated"


__all__ = [
    "World",
    "WorldFactory",
    "build_world",
    "deny_by_default_world",
]
