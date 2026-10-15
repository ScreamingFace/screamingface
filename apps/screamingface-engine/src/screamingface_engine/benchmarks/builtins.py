"""Concrete Benchmarks and immutable assets selected by this Engine deployment."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetBundle,
    BenchmarkDeployment,
    BenchmarkRegistration,
)
from screamingface_engine.benchmarks.discovery import discovered_registrations
from screamingface_engine.benchmarks.medxpert.definition import (
    ASSET_BUNDLE_ID as MEDXPERT_ASSET_BUNDLE_ID,
)
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT


def _prepare_medxpert(out: Path) -> Mapping[str, Any]:
    # WHY lazy: image-building code and its optional dataset dependency stay out of the runtime
    # import graph. The deployment carries the adapter, but imports it only when building assets.
    from screamingface_engine.benchmarks.medxpert.prepare import prepare

    return prepare(out)


MEDXPERT_ASSETS = BenchmarkAssetBundle(id=MEDXPERT_ASSET_BUNDLE_ID, prepare=_prepare_medxpert)

# WHY: this composition is the single source for both runtime discovery and image construction.
BUILTIN_REGISTRATIONS = (BenchmarkRegistration(benchmark=MEDXPERT, asset_bundle=MEDXPERT_ASSETS),)
# FEATURE: plugin-contributed benchmarks (OME-1115). The built-in tuple comes first and the
# discovered extensions after, so with the entry-point group empty (no plugin, or the
# plugin's optional dependencies absent) this deployment is byte-identical to before.
BUILTIN_DEPLOYMENT = BenchmarkDeployment((*BUILTIN_REGISTRATIONS, *discovered_registrations()))
BUILTIN_BENCHMARKS = BUILTIN_DEPLOYMENT.benchmarks

__all__ = ["BUILTIN_BENCHMARKS", "BUILTIN_DEPLOYMENT", "BUILTIN_REGISTRATIONS"]
