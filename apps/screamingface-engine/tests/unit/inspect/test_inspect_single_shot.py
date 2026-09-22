# pyright: reportMissingImports=false
# WHY file-level: the assembled board's scorer factory touches the `inspect` extra.
"""The imported-board assembly line — identity, routes, registration (spec §3/§6).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.single_shot import single_shot_board  # noqa: E402


def _board(
    key: str = "probe",
    *,
    case_count: int = 3,
    revision_pins: tuple[str, ...] = ("dataset", "rev-a", "split=test"),
):
    return single_shot_board(
        board_key=key,
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
    )


def test_identity_is_flat_and_revision_addressed() -> None:
    board = _board().benchmark
    assert board.id == "inspect-probe"
    assert len(board.revision) == 16
    int(board.revision, 16)


def test_revision_is_deterministic_and_pin_sensitive() -> None:
    """§6: same pins → same revision; changed pins → a new exam identity."""

    assert _board().benchmark.revision == _board().benchmark.revision
    other = single_shot_board(
        board_key="probe2",
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
    )
    assert other.benchmark.revision != _board().benchmark.revision


def test_registration_and_protocol_are_complete() -> None:
    board = _board("probe3")
    assert board.registration.benchmark is board.benchmark
    assert board.registration.asset_bundle.id == "inspect-probe3"
    assert board.benchmark.revision in board.aggregate_route
    board.benchmark.protocol(2)  # builds and type-checks without rendering


def test_case_count_rides_the_revision() -> None:
    """§6: the factory hashes the subset size ITSELF — a board author who forgets
    it in revision_pins cannot get a subset change with an unchanged exam identity."""

    assert (
        _board("count-a", case_count=3).benchmark.revision
        != _board("count-b", case_count=4).benchmark.revision
    )


def test_duplicate_board_key_with_different_pins_is_refused() -> None:
    """Copy-paste guard: a board module that kept the donor's key must fail loudly
    at assembly, never silently steal the first board's route resolution."""

    _board("dup")
    with pytest.raises(ValueError, match="already assembled"):
        _board("dup", revision_pins=("dataset", "rev-OTHER", "split=test"))


def test_a_revision_pin_with_a_newline_is_refused() -> None:
    """Newline-joined hashing: an embedded newline would let two different pin
    lists collide into one exam identity."""

    with pytest.raises(ValueError, match="newline"):
        _board("nl", revision_pins=("dataset", "rev-a\nsplit=test"))
