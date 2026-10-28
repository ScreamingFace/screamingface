"""Compose the app's provider registry: bundled plugins, then configured remote endpoints.

# FEATURE: hosted BYOM — the one place that knows the concrete remote-endpoint adapter. Core keeps
# its ports; this module, called by `create_app` before any auth router is mounted, wires them.
# INVARIANT: no config leaves the registry exactly as the bundled loader built it and installs the
# default policy. An explicit config is validated whole, and a collision registers no instance.
# INVARIANT: configuration is read once at startup; there is no hot reload in this slice.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .core.endpoint_access import PERMIT_ALL, EndpointAccessPolicy
from .core.registry import ProviderRegistry
from .plugins.remote_endpoint.definitions import RemoteEndpointConfig, RemoteEndpointConfigError
from .plugins.remote_endpoint.plugin import RemoteEndpointPlugin
from .plugins.remote_endpoint.policy import RemoteEndpointAccess
from .plugins.remote_endpoint.reader import read_remote_endpoint_config

logger = logging.getLogger(__name__)

# WHY a bound: shutdown waits for the endpoint closes even through a cancellation, but a close
# that never ends must not hold the process.
_CLOSE_DRAIN_SECONDS = 5.0


def compose_providers(
    registry: ProviderRegistry, *, config_path: Path | None
) -> EndpointAccessPolicy:
    """Add configured endpoints to ``registry`` and return the policy that gates them."""
    if config_path is None:
        return PERMIT_ALL
    return install_remote_endpoints(registry, read_remote_endpoint_config(config_path))


def install_remote_endpoints(
    registry: ProviderRegistry, config: RemoteEndpointConfig
) -> EndpointAccessPolicy:
    # WHY check before the first register: `ProviderRegistry.register` refuses one duplicate at a
    # time, which would leave the endpoints before it registered.
    bundled = {plugin.custom_llm_provider for plugin in registry.all()}
    if any(definition.id in bundled for definition in config.endpoints):
        raise RemoteEndpointConfigError("an endpoint id collides with a bundled provider")
    for definition in config.endpoints:
        enabled = config.grants[definition.id].enabled
        registry.register(RemoteEndpointPlugin(definition, enabled=enabled))
    return RemoteEndpointAccess(config.grants)


async def close_remote_endpoints(registry: ProviderRegistry) -> None:
    """Close every configured endpoint's HTTP client; the app's lifespan calls it at shutdown.

    # WHY here: this module is the one place that knows the concrete adapter, so the lifespan
    # needs no attribute probing on plugins and `compose_providers` still returns the policy.
    # WHY start every close before waiting for any: neither a failed close nor a cancelled
    # shutdown can then leave another endpoint open. `asyncio.wait`, unlike `gather`, cancels
    # none of the closes when the shutdown itself is cancelled.
    # WHY keep waiting through a cancellation, up to the bound: a loop that ends right after a
    # cancelled shutdown cancels every close still running, and httpx cannot finish a cancelled
    # close. The cancellation is raised once the closes are done or the bound has passed.
    """
    closing: dict[asyncio.Future[None], str] = {}
    for plugin in registry.all():
        if isinstance(plugin, RemoteEndpointPlugin):
            started = plugin.begin_close()
            if started is not None:
                closing[started] = plugin.custom_llm_provider
    if not closing:
        return
    cancelled = await _drain(set(closing), _CLOSE_DRAIN_SECONDS)
    for started, provider in closing.items():
        if not started.done():
            logger.warning("remote endpoint %s did not close within the shutdown bound", provider)
            continue
        error = None if started.cancelled() else started.exception()
        if error is not None:
            # INVARIANT: the error's text is not logged; it may carry the endpoint's origin.
            logger.warning(
                "remote endpoint %s did not close cleanly: %s", provider, type(error).__name__
            )
    if cancelled is not None:
        raise cancelled


async def _drain(
    pending: set[asyncio.Future[None]], seconds: float
) -> asyncio.CancelledError | None:
    """Wait until every close is done or ``seconds`` pass; return a cancellation that arrived."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    cancelled: asyncio.CancelledError | None = None
    while pending and (left := deadline - loop.time()) > 0:
        try:
            _, pending = await asyncio.wait(pending, timeout=left)
        except asyncio.CancelledError as exc:
            # INVARIANT: kept, not swallowed; the caller raises it after the closes.
            cancelled = exc
    return cancelled
