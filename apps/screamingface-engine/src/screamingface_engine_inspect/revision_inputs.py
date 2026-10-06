"""The imported benchmarks' own revision inputs: what this plugin decides, not upstream.

FEATURE: Imported Benchmarks. Every value here joins every Imported Benchmark's revision
(``single_shot``), so bumping one moves every route address on purpose. Moved verbatim from
the deleted pins.py lockfile (OME-1460): the per-Benchmark dataset facts now live on each
Task-replay declaration; these three are the plugin-wide ones, kept as other benchmark
families keep theirs (``benchmarks/*/revision_inputs.py``).
"""

from __future__ import annotations

from importlib.metadata import version

# WHY: prepare's emission rules are part of the benchmark; bump when they change.
PREPARER_REVISION = "inspect-single-shot-v1"
# WHY: the exchange itself — one candidate invocation, aggregate-side scoring.
PROTOCOL_REVISION = "inspect-single-shot-v1"


def pinned_inspect_packages() -> tuple[str, str]:
    """The installed inspect distributions as ``name==version`` identity strings.

    Spec §6 hashes "the pinned inspect-evals package digest"; with exact ``==``
    pins in the engine's ``inspect`` extra, the version string IS that identity.
    """

    return (
        f"inspect-ai=={version('inspect-ai')}",
        f"inspect-evals=={version('inspect-evals')}",
    )


__all__ = ["PREPARER_REVISION", "PROTOCOL_REVISION", "pinned_inspect_packages"]
