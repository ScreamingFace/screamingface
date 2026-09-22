"""The node tier (prd/03 §2.1): one world, built once, served over url4's own guards.

FEATURE (unit 3, prd/03): the deployed shape of the sync surface. The package keeps the import
path `screamingface_engine.world.node_tier` that the CLI and the tests use; the modules split by
concern (FX-21): `settings` (the ladder and its env names), `metrics`, `send` (observe, buffer,
remap, spill), `tier` (readiness and the ASGI app), `build` (the composition) and `serve` (the entry
point).

AIDEV-NOTE: `serve` below is the FUNCTION, re-exported under the same name as the `serve`
submodule. After this import, `node_tier.serve` is the function (`cli._node` relies on that).
Reach the submodule through `importlib.import_module` or `from ...node_tier.serve import ...`.
"""

from screamingface_engine.world.node_tier.build import build_node_tier
from screamingface_engine.world.node_tier.metrics import NodeMetrics, build_node_metrics
from screamingface_engine.world.node_tier.serve import serve
from screamingface_engine.world.node_tier.settings import (
    NODE_DEFAULT_RESULT_HARD_CAP_BYTES,
    NodeTierError,
    NodeTierSettings,
)
from screamingface_engine.world.node_tier.tier import NodeReadiness, NodeTier
from screamingface_engine.world.wire import AsgiApp

__all__ = [
    "NODE_DEFAULT_RESULT_HARD_CAP_BYTES",
    "AsgiApp",
    "NodeMetrics",
    "NodeReadiness",
    "NodeTier",
    "NodeTierError",
    "NodeTierSettings",
    "build_node_metrics",
    "build_node_tier",
    "serve",
]
