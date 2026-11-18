"""An outside contributor's Benchmark keeps its bare id and carries its author to the catalogue.

FEATURE: mark a Benchmark an outside contributor wrote as ``origin="external"`` and name them
in ``contributors``. STORY: as a reader of the catalogue, I see which Benchmarks came from
outside the team and who wrote them.

These live in the inspect lane because the id rule and the row assembler import the inspect
extra's packages.
"""

from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    BenchmarkSpec,
    imported_benchmark,
)
from screamingface_engine_inspect.single_shot import imported_benchmark_id  # noqa: E402


@pytest.mark.parametrize(
    ("origin", "benchmark_id"),
    [
        ("inspect_evals", "inspect-futurex_past"),
        ("screamingface", "futurex_past"),
        ("external", "futurex_past"),
    ],
)
def test_only_an_inspect_evals_import_takes_the_inspect_prefix(
    origin: str, benchmark_id: str
) -> None:
    # WHY: the prefix says "this eval came from inspect_evals". An external Benchmark did not,
    # and before this rule any origin that was not ours would have been published under it.
    assert imported_benchmark_id("futurex_past", origin) == benchmark_id  # type: ignore[arg-type]


def test_a_rows_contributors_field_defaults_to_none() -> None:
    # INVARIANT: no existing row gains a value, so no served catalogue entry changes.
    assert all(spec.contributors is None for spec in BENCHMARKS)
    assert "contributors" in {field.name for field in dataclasses.fields(BenchmarkSpec)}


def test_no_registered_benchmark_serves_contributors_yet() -> None:
    # The assembler passes the field through for every row; none declares it, so none serves
    # the key. A row that starts serving it must also flip its origin (the provenance rule).
    served = imported_benchmark("musique").benchmark.catalog_entry()

    assert served["origin"] == "screamingface"
    assert "contributors" not in served
