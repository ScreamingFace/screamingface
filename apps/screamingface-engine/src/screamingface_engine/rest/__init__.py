"""The screamingface-engine REST surface: run lifecycle, token minting, and model catalog routes.

Re-exports the FastAPI ``APIRouter``s (``router`` for run/token endpoints, ``catalog_router``
for the model catalog) and the ``SubscriberGate`` protocol so ``app.py`` can wire them without
reaching into the individual route modules.
"""

from screamingface_engine.rest.artifacts import router as artifact_router
from screamingface_engine.rest.benchmarks import router as benchmark_router
from screamingface_engine.rest.cache_versions import router as cache_version_router
from screamingface_engine.rest.catalog import router as catalog_router
from screamingface_engine.rest.connections import router as connection_router
from screamingface_engine.rest.interest import DenyAllGate, SubscriberGate
from screamingface_engine.rest.routes import router

__all__ = [
    "DenyAllGate",
    "SubscriberGate",
    "artifact_router",
    "benchmark_router",
    "cache_version_router",
    "catalog_router",
    "connection_router",
    "router",
]
