"""Prepare every immutable asset bundle required by the built-in Benchmark deployment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.deployment import (
    CHANGED_CASES_KEY,
    BenchmarkAssetPreparationError,
    BenchmarkAssetSummary,
)
from screamingface_engine.benchmarks.registry import DEFAULT_BENCHMARK_ASSETS_ROOT

#: Set to "1" only by the PR image job: after every bundle is prepared, fail if any was skipped
#: because its Cases changed, so the PR that changed them can't merge (OME-1273, spec R11).
FAIL_ON_CHANGED_CASES_ENV = "SCREAMINGFACE_FAIL_ON_CHANGED_CASES"


def prepare_builtin_assets(
    root: Path,
    on_prepared: Callable[[str, BenchmarkAssetSummary], None] | None = None,
    *,
    only: Sequence[str] | None = None,
) -> dict[str, BenchmarkAssetSummary]:
    """Build the built-in deployment's unique assets — all of them, or just those named."""

    return BUILTIN_DEPLOYMENT.prepare_assets(root, on_prepared, only=only)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_BENCHMARK_ASSETS_ROOT)
    parser.add_argument(
        "--bundle",
        action="append",
        dest="bundles",
        metavar="ID",
        help=(
            "prepare only this bundle, repeat for several; omit to prepare all of them, "
            "as the image build does. Use it to redo just the bundles a failed run left "
            "missing, instead of downloading every dataset again"
        ),
    )
    parser.add_argument(
        "--list-bundles",
        action="store_true",
        help="print every bundle id, one per line, and download nothing",
    )
    args = parser.parse_args(argv)

    if args.list_bundles:
        # WHY before anything else: a caller deciding WHICH bundles are still missing must be
        # able to ask without touching the asset tree.
        for bundle_id in sorted(BUILTIN_DEPLOYMENT.asset_bundle_ids):
            print(bundle_id)
        return 0

    only: tuple[str, ...] | None = tuple(args.bundles) if args.bundles else None
    if only is not None:
        # WHY validated HERE and not by catching the orchestrator's ValueError: a preparer
        # decoding a dataset row raises ValueError too (json.JSONDecodeError subclasses it),
        # so an except around the prepare step would relabel a malformed HF row as an operator typo
        # and discard its traceback — the exact laundering BenchmarkAssetPreparerContractError
        # exists to prevent. A typo is knowable before any download starts; check it there.
        unknown = sorted(set(only) - set(BUILTIN_DEPLOYMENT.asset_bundle_ids))
        if unknown:
            print(f"no such asset bundle(s): {', '.join(unknown)}", file=sys.stderr)
            return 1
    return _prepare(args.root, only)


def _prepare(root: Path, only: tuple[str, ...] | None) -> int:
    """Download and write out the selected benchmarks' datasets.

    Prints one JSON audit record per bundle as it lands, so a failure partway still leaves
    a record of everything that completed before it. `only` is None for all of them.
    """

    def emit(bundle: str, summary: BenchmarkAssetSummary) -> None:
        # WHY stream rather than print at the end: a refusal partway through must still leave
        # the completed bundles' evidence in the build log, which is the point of the record.
        record = {"root": str(root), "bundle": bundle, "summary": summary}
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
                    "root": str(root),
                    "bundle": bundle,
                    "summary_unreportable": type(exc).__name__,
                }
            )
        print(line, flush=True)

    try:
        prepared: dict[str, BenchmarkAssetSummary] = prepare_builtin_assets(root, emit, only=only)
    except BenchmarkAssetPreparationError as exc:
        print(f"benchmark asset preparation failed: {exc}", file=sys.stderr)
        return 1
    if os.environ.get(FAIL_ON_CHANGED_CASES_ENV) == "1":
        return _fail_on_changed_cases(prepared)
    return 0


def _fail_on_changed_cases(prepared: dict[str, BenchmarkAssetSummary]) -> int:
    """Strict mode: list every bundle skipped for changed Cases, and fail if there is any.

    WHY after the loop, not inside the preparer: one run reports every changed bundle, so a
    dependency bump that moves three Benchmarks shows all three in one CI log.
    """

    changed: dict[str, str] = {
        bundle: str(summary[CHANGED_CASES_KEY])
        for bundle, summary in prepared.items()
        if CHANGED_CASES_KEY in summary
    }
    for bundle, reason in changed.items():
        print(f"{bundle}: {reason}", file=sys.stderr)
    if not changed:
        return 0
    print(
        f"benchmark asset preparation failed: {len(changed)} bundle(s) have changed Cases "
        f"({FAIL_ON_CHANGED_CASES_ENV}=1)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["prepare_builtin_assets"]
