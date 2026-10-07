# pyright: reportMissingImports=false
# WHY file-level: the assembled benchmark's scorer factory touches the `inspect` extra.
"""The imported-benchmark assembly line — identity, routes, registration (spec §3/§6).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.single_shot import single_shot_benchmark  # noqa: E402


def _benchmark(
    key: str = "probe",
    *,
    case_count: int = 3,
    revision_pins: tuple[str, ...] = ("dataset", "rev-a", "split=test"),
):
    return single_shot_benchmark(
        benchmark_key=key,
        title="Probe",
        description="One non-comparable structural probe.",
        focus="Probing",
        dataset_url="https://example.com/probe",
        case_count=case_count,
        revision_pins=revision_pins,
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
    )


def test_identity_is_flat_and_revision_addressed() -> None:
    benchmark = _benchmark().benchmark
    assert benchmark.id == "inspect-probe"
    assert len(benchmark.revision) == 16
    int(benchmark.revision, 16)


def test_revision_is_deterministic_and_pin_sensitive() -> None:
    """§6: same pins → same revision; changed pins → a new benchmark identity."""

    assert _benchmark().benchmark.revision == _benchmark().benchmark.revision
    other = single_shot_benchmark(
        benchmark_key="probe2",
        title="Probe",
        description="One non-comparable structural probe.",
        focus="Probing",
        dataset_url="https://example.com/probe",
        case_count=3,
        revision_pins=("dataset", "rev-B", "split=test"),
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
    )
    assert other.benchmark.revision != _benchmark().benchmark.revision


def test_registration_and_protocol_are_complete() -> None:
    benchmark = _benchmark("probe3")
    assert benchmark.registration.benchmark is benchmark.benchmark
    assert benchmark.registration.asset_bundle.id == "inspect-probe3"
    assert benchmark.benchmark.revision in benchmark.aggregate_route
    benchmark.benchmark.protocol(2)  # builds and type-checks without rendering


def test_case_count_rides_the_revision() -> None:
    """§6: the factory hashes the subset size ITSELF — a benchmark author who forgets
    it in revision_pins cannot get a subset change with an unchanged benchmark identity."""

    assert (
        _benchmark("count-a", case_count=3).benchmark.revision
        != _benchmark("count-b", case_count=4).benchmark.revision
    )


def test_duplicate_benchmark_key_with_different_pins_is_refused() -> None:
    """Copy-paste guard: a benchmark module that kept the donor's key must fail loudly
    at assembly, never silently steal the first benchmark's route resolution."""

    _benchmark("dup")
    with pytest.raises(ValueError, match="already assembled"):
        _benchmark("dup", revision_pins=("dataset", "rev-OTHER", "split=test"))


def test_a_revision_pin_with_a_newline_is_refused() -> None:
    """Newline-joined hashing: an embedded newline would let two different pin
    lists collide into one benchmark identity."""

    with pytest.raises(ValueError, match="newline"):
        _benchmark("nl", revision_pins=("dataset", "rev-a\nsplit=test"))


def test_origin_defaults_to_inspect_evals_and_a_local_task_declares_screamingface() -> None:
    """INVARIANT (OME-1513): a Benchmark that arrives through this assembly is an import unless
    its row says otherwise — a local Task (our own eval in inspect's shape) is `screamingface`
    origin, which is what lets it ship with no inspect porter list (provenance rule)."""

    assert _benchmark().benchmark.origin == "inspect_evals"
    local = single_shot_benchmark(
        benchmark_key="probe-local",
        title="Probe",
        description="One non-comparable structural probe.",
        focus="Probing",
        dataset_url="https://example.com/probe",
        case_count=3,
        revision_pins=("dataset", "rev-a"),
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, assets: None,
        with_check_surface=False,
        difficulty="easy",
        origin="screamingface",
    )
    assert local.benchmark.origin == "screamingface"
