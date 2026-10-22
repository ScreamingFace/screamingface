# pyright: reportMissingImports=false
# WHY file-level: the assembly test imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Which imported rows are Unlisted — pinned by name (OME-1714).

INVARIANT: the Unlisted set is an owner decision written on the row, never inferred from a
family or a content warning. Adding a row to it, or taking one out, is a diff on this
literal — the review act. Today it is exactly the three WMDP Benchmarks: product asked for
them off the public catalogue (hazardous-knowledge elicitation reads as an invitation).

The set test reads the spec rows only, so it runs in the extra-less CI lane; the assembly
test needs the `inspect` extra.
"""

from __future__ import annotations

import pytest

from screamingface_engine_inspect.benchmarks import BENCHMARKS

#: key → Unlisted, for every row that carries the mark (OME-1714).
_UNLISTED: frozenset[str] = frozenset({"wmdp_bio", "wmdp_chem", "wmdp_cyber"})


def test_exactly_the_wmdp_rows_are_unlisted() -> None:
    unlisted: set[str] = {spec.key for spec in BENCHMARKS if spec.unlisted}

    assert unlisted == set(_UNLISTED)


def test_the_assembled_benchmark_carries_the_rows_mark() -> None:
    pytest.importorskip("inspect_ai")
    pytest.importorskip("inspect_evals")
    from screamingface_engine_inspect.benchmarks import imported_benchmark

    # INVARIANT: the factory threads the row's mark through unchanged — a row that says
    # unlisted assembles an unlisted Benchmark, and a row that does not stays listed.
    assert imported_benchmark("wmdp_bio").benchmark.unlisted is True
    assert imported_benchmark("gsm8k").benchmark.unlisted is False
