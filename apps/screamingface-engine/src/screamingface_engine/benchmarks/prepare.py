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
        # WHY `default=str` AND the guard: this runs inside the preparation loop, so a record
        # json cannot encode would abort every bundle after this one. `default=` covers values
        # but is NEVER consulted for keys, and cannot rescue a circular or over-deep summary
        # either — so the encoder itself is fenced. A reporting fault must cost fidelity in one
        # record, never the assets the image is being built to carry.
        try:
            line = json.dumps(record, default=str)
        except (TypeError, ValueError, RecursionError) as exc:
            # The bundle still completed; say so, and name the reporting fault instead.
            line = json.dumps(
                {
                    "root": str(args.root),
                    "bundle": bundle,
                    "summary_unreportable": type(exc).__name__,
                }
            )
        print(line, flush=True)

    try:
        prepare_builtin_assets(args.root, emit)
    except BenchmarkAssetPreparationError as exc:
        print(f"benchmark asset preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["prepare_builtin_assets"]
