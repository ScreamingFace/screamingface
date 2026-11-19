"""build_result with a run's result spool (memory fix 3, OME-1835, wave 3).

WHY these tests: a body that is the run spool's issued reference is the streamed result, so
build_result hands back that ticket with no second encode or write. Any other body, once the
spool issued a reference, fails closed with `result_spool_unredeemed`. A spool that issued
nothing, or no spool at all, keeps today's three-way verdict unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.spool import ResultSpool
from screamingface_engine.runner.executor import _RunState
from url4.core.errors import ResolutionError


def test_a_redeemed_reference_returns_its_ticket_without_a_second_write(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "spool")
    spool = ResultSpool(store, inline_cap=10, hard_cap=10_000)
    ref = spool.deliver(lambda write: write("x" * 50))
    held = tmp_path / "held"

    result = _RunState().build_result(
        ref,
        inline_cap=10,
        hard_cap=10_000,
        store=FilesystemArtifactStore(held),
        media_type="application/json",
        spool=spool,
    )

    assert result.artifact == spool.redeem(ref)
    assert result.body is None
    assert result.media_type == "application/json"
    assert not held.exists()


def test_an_issued_but_unredeemed_reference_fails_the_run(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "spool")
    spool = ResultSpool(store, inline_cap=10, hard_cap=10_000)
    spool.deliver(lambda write: write("x" * 50))

    with pytest.raises(ResolutionError) as raised:
        _RunState().build_result(
            '{"other":1}',
            inline_cap=10,
            hard_cap=10_000,
            store=store,
            spool=spool,
        )

    assert raised.value.code == "result_spool_unredeemed"
    assert raised.value.permanent is True


def test_a_spool_that_issued_nothing_keeps_todays_paths(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "spool")
    spool = ResultSpool(store, inline_cap=10, hard_cap=20)

    inline = _RunState().build_result("small", inline_cap=10, hard_cap=20, store=store, spool=spool)
    spilled = _RunState().build_result(
        "x" * 15, inline_cap=10, hard_cap=20, store=store, spool=spool
    )
    assert inline.body == "small"
    assert spilled.artifact is not None
    assert spilled.artifact.size_bytes == 15

    with pytest.raises(ResolutionError) as raised:
        _RunState().build_result("x" * 50, inline_cap=10, hard_cap=20, store=store, spool=spool)
    assert raised.value.code == "result_too_large"


def test_no_spool_is_todays_build_result(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "spool")

    inline = _RunState().build_result("small", inline_cap=10, hard_cap=20, store=store)
    spilled = _RunState().build_result("x" * 15, inline_cap=10, hard_cap=20, store=store)
    assert inline.body == "small"
    assert spilled.artifact is not None
    assert spilled.artifact.size_bytes == 15

    with pytest.raises(ResolutionError) as raised:
        _RunState().build_result("x" * 50, inline_cap=10, hard_cap=20, store=store)
    assert raised.value.code == "result_too_large"
