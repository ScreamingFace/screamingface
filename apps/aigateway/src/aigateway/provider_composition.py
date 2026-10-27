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
    """
    closing: dict[asyncio.Future[None], str] = {}
    for plugin in registry.all():
        if isinstance(plugin, RemoteEndpointPlugin):
            started = plugin.begin_close()
            if started is not None:
                closing[started] = plugin.custom_llm_provider
    if not closing:
        return
    await asyncio.wait(closing)
    for started, provider in closing.items():
        error = None if started.cancelled() else started.exception()
        if error is not None:
            # INVARIANT: the error's text is not logged; it may carry the endpoint's origin.
            logger.warning(
                "remote endpoint %s did not close cleanly: %s", provider, type(error).__name__
            )
