"""Prepare every immutable asset bundle required by the built-in Benchmark deployment."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetPreparationError,
    BenchmarkAssetSummary,
)
from screamingface_engine.benchmarks.registry import DEFAULT_BENCHMARK_ASSETS_ROOT


def prepare_builtin_assets(
    root: Path,
    on_prepared: Callable[[str, BenchmarkAssetSummary], None] | None = None,
) -> dict[str, BenchmarkAssetSummary]:
    """Build all unique assets declared by the built-in deployment."""

    return BUILTIN_DEPLOYMENT.prepare_assets(root, on_prepared)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_BENCHMARK_ASSETS_ROOT)
    args = parser.parse_args(argv)

    def emit(bundle: str, summary: BenchmarkAssetSummary) -> None:
        # WHY stream rather than print at the end: a refusal partway through must still leave
        # the completed bundles' evidence in the build log, which is the point of the record.
        record = {"root": str(args.root), "bundle": bundle, "summary": summary}
        print(json.dumps(record), flush=True)

    try:
        prepare_builtin_assets(args.root, emit)
    except BenchmarkAssetPreparationError as exc:
        print(f"benchmark asset preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["prepare_builtin_assets"]
