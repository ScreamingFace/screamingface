"""The picture notebook picks which Benchmarks to run without trusting the catalogue on a Mac.

INVARIANT under test: on a local stack on a Mac, the three Benchmarks whose Case Digest is
sealed on Linux are skipped, even though the catalogue lists them. A local Engine lists every
Benchmark it knows, prepared or not, so a notebook that trusted the listing would run them and
fail on missing Cases, with the wrong reason printed (OME-1787).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_NOTEBOOK = Path(__file__).parent.parent / "examples" / "18_picture_benchmarks.ipynb"
_ALL_FIVE = (
    "inspect-lab_bench_figqa",
    "inspect-lab_bench_tableqa",
    "inspect-mmmu_multiple_choice",
    "inspect-mmmu_open",
    "inspect-mathvista",
)
_LINUX_SEALED = {"inspect-mmmu_multiple_choice", "inspect-mmmu_open", "inspect-mathvista"}


def _selection_cell() -> str:
    """The generated code cell that decides which picture Benchmarks run."""
    cells: list[dict[str, Any]] = json.loads(_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    sources: list[str] = [
        "".join(cell["source"]) for cell in cells if cell.get("cell_type") == "code"
    ]
    matches: list[str] = [source for source in sources if "SEALED_ON_LINUX =" in source]
    assert len(matches) == 1
    return matches[0]


def _run_selection(target: str, system: str, listed: tuple[str, ...]) -> dict[str, Any]:
    """Run the selection cell against a stand-in catalogue, as on a given machine and target."""
    # Stand-ins: the catalogue is what the Engine lists (all imported, so the inspect extra is
    # there), and `platform.system()` is the machine the notebook's kernel runs on.
    catalogue: list[SimpleNamespace] = [
        SimpleNamespace(id=benchmark_id, origin="inspect_evals") for benchmark_id in listed
    ]
    namespace: dict[str, Any] = {
        "sf": SimpleNamespace(benchmarks=SimpleNamespace(list=lambda: catalogue)),
        "platform": SimpleNamespace(system=lambda: system),
        "TARGET": target,
    }
    exec(_selection_cell(), namespace)  # noqa: S102 -- our own generated cell, stand-ins only
    return namespace


def test_a_local_mac_skips_the_linux_sealed_benchmarks_although_the_catalogue_lists_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace: dict[str, Any] = _run_selection("local", "Darwin", _ALL_FIVE)

    assert namespace["served"] == ["inspect-lab_bench_figqa", "inspect-lab_bench_tableqa"]
    out: str = capsys.readouterr().out
    for benchmark_id in _LINUX_SEALED:
        assert f"skipped  {benchmark_id}: its Case Digest is sealed on Linux" in out


@pytest.mark.parametrize(("target", "system"), [("dev", "Darwin"), ("local", "Linux")])
def test_every_listed_benchmark_runs_off_a_local_mac(target: str, system: str) -> None:
    namespace: dict[str, Any] = _run_selection(target, system, _ALL_FIVE)

    assert namespace["served"] == list(_ALL_FIVE)


def test_a_benchmark_the_engine_does_not_list_is_named_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace: dict[str, Any] = _run_selection("dev", "Darwin", _ALL_FIVE[:4])

    assert namespace["served"] == list(_ALL_FIVE[:4])
    assert "missing  inspect-mathvista: not merged into this Engine yet" in capsys.readouterr().out
