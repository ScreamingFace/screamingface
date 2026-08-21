"""Compose runtime Benchmarks with the immutable assets their deployment requires."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.registry import BenchmarkRegistry

type BenchmarkAssetSummary = Mapping[str, Any]
type BenchmarkAssetPreparer = Callable[[Path], BenchmarkAssetSummary]

_ASSET_BUNDLE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")


class BenchmarkAssetPreparationError(RuntimeError):
    """An expected, operator-readable refusal to prepare a benchmark asset bundle."""


class BenchmarkAssetPreparerContractError(TypeError):
    """A preparer broke the port contract — a defect in this codebase, not an asset refusal.

    WHY a separate hierarchy: `BenchmarkAssetPreparationError` is the orchestrator CLI's exit-1
    channel for dataset and answer-key drift, reported without a traceback. A wrongly-typed
    preparer is a programming defect; laundering it through that channel sends an operator
    hunting for dataset drift that does not exist. `TypeError` keeps it recognisable as one.
    """


@dataclass(frozen=True, slots=True)
class BenchmarkAssetBundle:
    """One physical directory of immutable assets, shared by one or more Benchmarks."""

    id: str
    prepare: BenchmarkAssetPreparer

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _ASSET_BUNDLE_ID.fullmatch(self.id) is None:
            raise ValueError("BenchmarkAssetBundle id must be one lowercase path-safe identifier")
        if not callable(self.prepare):
            raise TypeError("BenchmarkAssetBundle prepare must be callable")


@dataclass(frozen=True, slots=True)
class BenchmarkRegistration:
    """One runtime Benchmark plus the physical asset bundle it requires.

    ``asset_bundle`` deliberately has no default. Every registered built-in Benchmark therefore
    names a preparation path at construction; omission cannot masquerade as an assetless protocol.
    """

    benchmark: Benchmark
    asset_bundle: BenchmarkAssetBundle

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark, Benchmark):
            raise TypeError("BenchmarkRegistration benchmark must be a Benchmark")
        if not isinstance(self.asset_bundle, BenchmarkAssetBundle):
            raise TypeError("BenchmarkRegistration asset_bundle must be a BenchmarkAssetBundle")


class BenchmarkDeployment:
    """One validated deployment of Benchmarks and their build-time assets.

    The runtime consumes ``benchmarks``. The benchmark-image build calls ``prepare_assets``.
    Both views derive from the same registrations, so the image cannot advertise a Benchmark
    whose asset requirement was omitted from a parallel Dockerfile list.
    """

    __slots__ = ("_asset_bundles", "_benchmarks", "_registrations")

    def __init__(self, registrations: Iterable[BenchmarkRegistration]) -> None:
        selected = tuple(registrations)
        self._registrations = selected
        self._benchmarks = BenchmarkRegistry(registration.benchmark for registration in selected)

        bundles: dict[str, BenchmarkAssetBundle] = {}
        for registration in selected:
            bundle = registration.asset_bundle
            installed = bundles.get(bundle.id)
            if installed is not None and installed is not bundle:
                raise ValueError(f"conflicting BenchmarkAssetBundles declare id {bundle.id!r}")
            bundles[bundle.id] = bundle
        self._asset_bundles = tuple(bundles[bundle_id] for bundle_id in sorted(bundles))

    @property
    def benchmarks(self) -> BenchmarkRegistry:
        """The runtime registry derived from this deployment's registrations."""

        return self._benchmarks

    @property
    def registrations(self) -> tuple[BenchmarkRegistration, ...]:
        """The immutable composition declarations, exposed for deployment audits."""

        return self._registrations

    def prepare_assets(
        self,
        root: Path,
        on_prepared: Callable[[str, BenchmarkAssetSummary], None] | None = None,
    ) -> dict[str, BenchmarkAssetSummary]:
        """Prepare every unique bundle and retain its audit summary in stable ID order.

        WHY `on_prepared`: bundles write real files as they go, so a later bundle's refusal
        must not erase the evidence for the ones that already landed. The callback fires as
        each bundle completes, letting a caller stream its audit record before any failure —
        while the I/O decision stays with the caller and out of this orchestrator.
        """

        root.mkdir(parents=True, exist_ok=True)
        prepared: dict[str, BenchmarkAssetSummary] = {}
        for bundle in self._asset_bundles:
            out = root / bundle.id
            out.mkdir(parents=True, exist_ok=True)
            observed = bundle.prepare(out)
            if not isinstance(observed, Mapping):
                raise BenchmarkAssetPreparerContractError(
                    f"bundle {bundle.id!r} preparer returned "
                    f"{type(observed).__name__}, not a summary mapping"
                )
            # INVARIANT: snapshot the adapter's own top-level observations so a later mutation
            # of the mapping it handed back cannot rewrite this bake's reported evidence.
            # AIDEV-NOTE: shallow by design — a preparer must build its values fresh rather
            # than hand back a container it keeps mutating. Deep-copying arbitrary adapter
            # values would be the orchestrator guessing at their semantics.
            summary = dict(observed)
            prepared[bundle.id] = summary
            if on_prepared is not None:
                on_prepared(bundle.id, summary)
        return prepared


__all__ = [
    "BenchmarkAssetBundle",
    "BenchmarkAssetPreparer",
    "BenchmarkAssetPreparationError",
    "BenchmarkAssetPreparerContractError",
    "BenchmarkAssetSummary",
    "BenchmarkDeployment",
    "BenchmarkRegistration",
]
