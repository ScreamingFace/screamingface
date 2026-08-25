"""Benchmark discovery through the lazy default Client."""

from __future__ import annotations

from collections.abc import Sequence

from screamingface._default_client import default_client
from screamingface.discovery import Benchmark


def list() -> Sequence[Benchmark]:
    """List the Benchmarks currently exposed by the configured SF Engine."""

    return default_client().benchmarks.list()


def get(benchmark_id: str) -> Benchmark:
    """Fetch one Benchmark's identity card by its catalog id."""

    return default_client().benchmarks.get(benchmark_id)


__all__ = ["get", "list"]
