"""Compose the app's provider registry: bundled plugins, then configured remote endpoints.

# FEATURE: hosted BYOM — the one place that knows the concrete remote-endpoint adapter. Core keeps
# its ports; this module, called by `create_app` before any auth router is mounted, wires them.
# INVARIANT: no config leaves the registry exactly as the bundled loader built it and installs the
# default policy. An explicit config is validated whole, and a collision registers no instance.
# INVARIANT: configuration is read once at startup; there is no hot reload in this slice.
"""

from __future__ import annotations

from pathlib import Path

from .core.endpoint_access import PERMIT_ALL, EndpointAccessPolicy
from .core.registry import ProviderRegistry
from .plugins.remote_endpoint.definitions import RemoteEndpointConfig, RemoteEndpointConfigError
from .plugins.remote_endpoint.plugin import RemoteEndpointPlugin
from .plugins.remote_endpoint.policy import RemoteEndpointAccess
from .plugins.remote_endpoint.reader import read_remote_endpoint_config


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
        registry.register(RemoteEndpointPlugin(definition))
    return RemoteEndpointAccess(config.grants)
