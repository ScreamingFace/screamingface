"""Discover benchmark deployments contributed by installed plugin packages.

Think of the registry as a loading dock: plugin packages (sealed crates carrying their
own dependencies) declare an entry point in the ``screamingface_engine.benchmark_deployments``
group, and this module forklifts whatever crates are installed into the deployment —
without the core import graph ever learning a plugin's name.

FEATURE: imported inspect_evals benchmarks (OME-1115, spec
``docs/spec/2026-09-09-OME-1113-inspect-evals-import.md`` §3.1) ship as the first such
crate — and the spec's own acceptance grep proves this module never names it.

INVARIANT (hexagonal rule): core defines this port and the generic loop ONLY. No plugin
name, no plugin-specific exception policy — a plugin whose optional dependencies are
absent contributes an EMPTY iterable itself; a plugin that raises is a real defect and
surfaces loudly at composition time.

INVARIANT: with the group empty, the composed deployment is byte-identical to the
static registrations — an engine installed without any plugin extra behaves exactly as
before this seam existed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration

#: The entry-point group plugins register into (spec §3.1) — each entry point resolves
#: to a zero-argument callable returning an iterable of ``BenchmarkRegistration``.
ENTRY_POINT_GROUP = "screamingface_engine.benchmark_deployments"


def _installed_entry_points(group: str) -> Iterable[Any]:
    """The interpreter's installed entry points for ``group`` — the production reader."""

    return entry_points(group=group)


def discovered_registrations(
    *,
    entry_points_for_group: Callable[[str], Iterable[Any]] = _installed_entry_points,
) -> tuple[BenchmarkRegistration, ...]:
    """Load every plugin's contributed registrations, in a deterministic order.

    Stage 1 — read the group and sort by entry-point name, so the composed deployment
              never depends on installation order.
    Stage 2 — per entry point: ``load()`` the provider callable and call it; the plugin
              decides what it can offer (an extra-less install yields an empty iterable).
    Stage 3 — refuse, naming the entry point, anything that is not a
              ``BenchmarkRegistration`` — a broken plugin fails composition, never a run.

    Args:
        entry_points_for_group: injectable reader for tests; production reads the
            interpreter's installed distribution metadata.

    Returns:
        Every contributed registration, ready to extend the static deployment.
    """

    registrations: list[BenchmarkRegistration] = []
    for entry_point in sorted(
        entry_points_for_group(ENTRY_POINT_GROUP), key=lambda point: point.name
    ):
        provider: Callable[[], Iterable[object]] = entry_point.load()
        for contributed in provider():
            if not isinstance(contributed, BenchmarkRegistration):
                raise TypeError(
                    f"benchmark deployment entry point {entry_point.name!r} contributed "
                    f"{type(contributed).__name__}, not a BenchmarkRegistration"
                )
            registrations.append(contributed)
    return tuple(registrations)


__all__ = ["ENTRY_POINT_GROUP", "discovered_registrations"]
