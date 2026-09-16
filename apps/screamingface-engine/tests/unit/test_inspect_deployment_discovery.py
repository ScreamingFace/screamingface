"""The generic benchmark-deployment discovery seam (OME-1115, spec §3.1).

FEATURE: imported inspect_evals benchmarks ship in a sealed plugin package; engine core
gains ONE generic entry-point discovery loop and zero knowledge of any plugin's name.

INVARIANT the suite defends: with the entry-point group empty, the composed
BUILTIN_DEPLOYMENT is byte-identical to the built-in registration tuple — installing the
engine without the `inspect` extra changes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.builtins import (
    BUILTIN_DEPLOYMENT,
    BUILTIN_REGISTRATIONS,
)
from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetBundle,
    BenchmarkRegistration,
)
from screamingface_engine.benchmarks.discovery import (
    ENTRY_POINT_GROUP,
    discovered_registrations,
)
from screamingface_engine.benchmarks.draco.definition import DRACO


class _FakeEntryPoint:
    """One synthetic entry point: `load()` returns the plugin's provider callable."""

    def __init__(self, name: str, provider: Any) -> None:
        self.name = name
        self._provider = provider

    def load(self) -> Any:
        return self._provider


def _registration() -> BenchmarkRegistration:
    # WHY a real Benchmark (DRACO): BenchmarkRegistration type-checks its fields, and
    # this suite is about the discovery loop, not about authoring a fake board.
    bundle = BenchmarkAssetBundle(id="fake-plugin-bundle", prepare=lambda out: {})
    return BenchmarkRegistration(benchmark=DRACO, asset_bundle=bundle)


def test_group_name_is_the_spec_contract() -> None:
    """Spec §3.1 names the group; plugins register against this exact string."""

    assert ENTRY_POINT_GROUP == "screamingface_engine.benchmark_deployments"


def test_empty_group_discovers_nothing() -> None:
    def none_for_group(group: str) -> Iterable[Any]:
        assert group == ENTRY_POINT_GROUP
        return ()

    assert discovered_registrations(entry_points_for_group=none_for_group) == ()


def test_synthetic_entry_point_registrations_appear_in_order() -> None:
    first = _registration()
    second = _registration()

    def fake_group(group: str) -> Iterable[Any]:
        return (
            _FakeEntryPoint("b-plugin", lambda: (second,)),
            _FakeEntryPoint("a-plugin", lambda: (first,)),
        )

    # INVARIANT: discovery order is deterministic (sorted by entry-point name), so the
    # composed deployment does not depend on installation order.
    assert discovered_registrations(entry_points_for_group=fake_group) == (first, second)


def test_non_registration_contribution_is_refused_by_name() -> None:
    def fake_group(group: str) -> Iterable[Any]:
        return (_FakeEntryPoint("broken-plugin", lambda: ("not-a-registration",)),)

    with pytest.raises(TypeError, match="broken-plugin"):
        discovered_registrations(entry_points_for_group=fake_group)


def test_builtin_deployment_is_builtins_plus_discovered() -> None:
    """The composition rule itself: built-in tuple first, discovered extensions after.

    With no plugin installed (or the plugin's optional deps absent) the discovered part
    is empty and the deployment is byte-identical to the built-in tuple.
    """

    registrations = BUILTIN_DEPLOYMENT.registrations
    assert registrations[: len(BUILTIN_REGISTRATIONS)] == BUILTIN_REGISTRATIONS
    for extra in registrations[len(BUILTIN_REGISTRATIONS) :]:
        assert isinstance(extra, BenchmarkRegistration)


def test_engine_core_never_imports_the_inspect_plugin() -> None:
    """Spec §8.4 — `grep -r "screamingface_engine_inspect" src/screamingface_engine/` is empty."""

    core_root = Path(__file__).resolve().parents[2] / "src" / "screamingface_engine"
    assert core_root.is_dir()
    offenders = [
        str(path)
        for path in core_root.rglob("*.py")
        if "screamingface_engine_inspect" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
