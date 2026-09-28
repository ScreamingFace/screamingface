"""The plugin's loading-dock manifest: what this crate contributes to the deployment.

The entry point in ``screamingface_engine.benchmark_deployments`` resolves here. The
plugin ships in the same wheel as the engine, so the entry point ALWAYS exists — the
optional part is the ``inspect`` extra's dependencies. This module therefore owns the
"am I usable?" decision: the engine's discovery loop stays generic, and an extra-less
install gets an empty contribution instead of an ImportError.

INVARIANT: importable with NO inspect distribution installed. Everything that touches
``inspect_ai`` / ``inspect_evals`` is imported lazily, behind the availability check.
"""

from __future__ import annotations

from importlib.util import find_spec

from screamingface_engine.benchmarks.deployment import BenchmarkRegistration

_REQUIRED_DISTRIBUTIONS = ("inspect_ai", "inspect_evals")


def inspect_available() -> bool:
    """Whether the ``inspect`` extra's dependencies are importable in this install."""

    return all(find_spec(name) is not None for name in _REQUIRED_DISTRIBUTIONS)


def registrations() -> tuple[BenchmarkRegistration, ...]:
    """Every imported board this plugin contributes — empty without the ``inspect`` extra.

    WHY the emptiness lives HERE and not in the discovery loop: the plugin is the only
    party that knows its own optional dependencies. Core discovery loads and calls every
    installed entry point with no exception policy, so a plugin that cannot serve must
    answer "nothing" rather than raise.
    """

    if not inspect_available():
        return ()
    # Lazy: boards import inspect_ai at module import, legal only past the check above.
    from screamingface_engine_inspect.boards import board_registrations

    return board_registrations()


__all__ = ["inspect_available", "registrations"]
