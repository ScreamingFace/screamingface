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
    # INVARIANT: a row that does not mention the field serves no contributors key, so adding
    # the field changed no existing catalogue entry.
    [field] = [f for f in dataclasses.fields(BenchmarkSpec) if f.name == "contributors"]

    assert field.default is None


def test_only_an_external_row_names_contributors() -> None:
    # The provenance rule refuses the field on any other origin when the row is assembled;
    # this reads the table itself, so a mistake shows without assembling 96 rows.
    assert all(spec.origin == "external" for spec in BENCHMARKS if spec.contributors is not None)


def test_a_team_written_row_serves_no_contributors() -> None:
    served = imported_benchmark("musique").benchmark.catalog_entry()

    assert served["origin"] == "screamingface"
    assert "contributors" not in served
