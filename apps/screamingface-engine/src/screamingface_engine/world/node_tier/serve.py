"""The `screamingface-engine node` entry point: the tier under uvicorn, metrics on their own port.

FEATURE (unit 3, prd/03 §2.1): the deployed shape of the sync surface. The mount port serves
the tier (mounts plus `/healthz`, `/livez`, `/readyz`); `/metrics` has its own port (FX-5, RD2)
so the chart can give it its own NetworkPolicy rule.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from types import FrameType
from typing import TYPE_CHECKING

from prometheus_client import start_http_server

from screamingface_engine.world.node_tier.build import build_node_tier
from screamingface_engine.world.node_tier.settings import NodeTierSettings
from screamingface_engine.world.node_tier.tier import NodeReadiness

if TYPE_CHECKING:
    import uvicorn

logger = logging.getLogger(__package__)


def serve(env: Mapping[str, str] | None = None) -> None:
    """Run the node tier under uvicorn — the `screamingface-engine node` entry point.

    uvicorn is imported lazily, like every other serving entry in this package, so importing
    the tier for a test or a config check does not require the server extra.
    """
    asyncio.run(_serve(env if env is not None else os.environ))


async def _serve(env: Mapping[str, str]) -> None:
    import uvicorn

    settings = NodeTierSettings.from_env(env)
    tier = await build_node_tier(env=env, settings=settings)
    logger.info(
        "node tier serving mounts=%d request_timeout_s=%.0f aigateway_timeout_s=%.0f "
        "max_inflight=%d",
        len(tier.mounts),
        settings.request_timeout_s,
        settings.aigateway_timeout_s,
        settings.max_inflight,
    )
    # FX-5: `/metrics` is served here, on its own port, and never on the mount port.
    start_http_server(settings.metrics_port, addr=settings.host, registry=tier.metrics.registry)
    server = _draining_server(
        uvicorn.Config(tier, host=settings.host, port=settings.port, log_level=settings.log_level),
        tier.readiness,
    )
    try:
        await server.serve()
    finally:
        await tier.aclose()


def _draining_server(config: uvicorn.Config, readiness: NodeReadiness) -> uvicorn.Server:
    """A uvicorn server that marks the tier draining the moment a shutdown signal arrives.

    WHY at the signal and not only at lifespan shutdown (FX-4, RD2): uvicorn runs the lifespan
    shutdown only AFTER it has stopped accepting and finished the in-flight requests. `/readyz`
    must fail from the first moment of the drain, so the Service stops sending new traffic
    while the pod finishes what it has.
    """
    import uvicorn

    class _DrainingServer(uvicorn.Server):
        def handle_exit(self, sig: int, frame: FrameType | None) -> None:
            readiness.drain()
            super().handle_exit(sig, frame)

    return _DrainingServer(config)
