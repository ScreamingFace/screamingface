"""A run's own resident memory, logged at run start, after the Cases load and at run end.

FEATURE (memory diagnostics, epic OME-1314): a FigQA run was killed at 2,862 MiB with only
~2.1 GiB explained; these lines state the process baseline and the Cases cost directly.
"""

import logging
import resource
from pathlib import Path

import pytest
from test_client_provenance import _FailingExecutor

from screamingface_engine import process_memory
from screamingface_engine.benchmarks.case_selection import cases_handler
from screamingface_engine.runner.main import _run_and_log, params_from_env
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from url4.core.errors import ResolutionError
from url4.peer.server import Request

LOGGER = "screamingface_engine.process_memory"
MIB = 2**20


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


# --- current resident memory (/proc/self/statm) ------------------------------------------


def test_current_resident_bytes_are_statm_resident_pages_times_page_size(tmp_path: Path) -> None:
    statm = tmp_path / "statm"
    statm.write_text("250000 1000 300 10 0 900 0\n")
    assert process_memory.current_resident_bytes(statm, page_size=4096) == 1000 * 4096


@pytest.mark.parametrize("content", [None, "", "garbage", "12"])
def test_an_unreadable_statm_is_unknown_never_zero(tmp_path: Path, content: str | None) -> None:
    """INVARIANT: macOS has no /proc — the reading is None ("unknown"), never a fake 0."""
    statm = tmp_path / "statm"
    if content is not None:
        statm.write_text(content)
    assert process_memory.current_resident_bytes(statm, page_size=4096) is None


def test_current_resident_bytes_reads_this_process_on_linux() -> None:
    reading = process_memory.current_resident_bytes()
    if Path("/proc/self/statm").is_file():
        assert reading is not None and reading > 0
    else:
        assert reading is None


# --- peak resident memory (getrusage ru_maxrss) ------------------------------------------


@pytest.mark.parametrize(
    "platform, maxrss, expected",
    [("linux", 2048, 2048 * 1024), ("darwin", 2048 * 1024, 2048 * 1024)],
)
def test_peak_normalises_ru_maxrss_units_per_platform(
    platform: str, maxrss: int, expected: int
) -> None:
    """WHY: Linux reports ru_maxrss in KiB, macOS in bytes."""
    assert process_memory.peak_resident_bytes(maxrss=maxrss, platform=platform) == expected


def test_peak_reads_this_process_and_is_at_least_current() -> None:
    peak = process_memory.peak_resident_bytes()
    assert peak >= resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    current = process_memory.current_resident_bytes()
    if current is not None:
        assert peak >= current


# --- the log line ------------------------------------------------------------------------


def test_the_line_names_the_point_and_both_readings_in_mib(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(process_memory, "current_resident_bytes", lambda: 812 * MIB + MIB // 2)
    monkeypatch.setattr(process_memory, "peak_resident_bytes", lambda: 903 * MIB)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        process_memory.log_process_memory("cases_loaded", cases=1200)
    assert _lines(caplog) == [
        "process memory point=cases_loaded rss_mib=812.5 peak_rss_mib=903.0 cases=1200"
    ]


def test_an_unknown_current_reading_logs_unknown(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(process_memory, "current_resident_bytes", lambda: None)
    monkeypatch.setattr(process_memory, "peak_resident_bytes", lambda: 64 * MIB)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        process_memory.log_process_memory("run_start")
    assert _lines(caplog) == ["process memory point=run_start rss_mib=unknown peak_rss_mib=64.0"]


def test_a_failing_reading_never_breaks_the_run(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: diagnostics may degrade, never fail the run they describe."""

    def broken() -> int:
        raise OSError("no rusage")

    monkeypatch.setattr(process_memory, "peak_resident_bytes", broken)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        process_memory.log_process_memory("run_end")
    assert not [line for line in _lines(caplog) if line.startswith("process memory point=")]


# --- wiring: run start / run end ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_logs_memory_at_start_and_end_even_when_it_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    params = params_from_env(decode_message(encode_message("mem-topic", "'hi'", 60)))
    stream = InMemoryEventStream()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await _run_and_log(OperationCapturingExecutor(_FailingExecutor()), stream, params, None)
    points = [line.split()[2] for line in _lines(caplog)]
    assert points == ["point=run_start", "point=run_end"]


# --- wiring: right after the Cases load --------------------------------------------------


def test_the_cases_route_logs_memory_with_the_case_count_and_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = '[{"id": 1, "input": "SECRET-PROMPT-ONE"}, {"id": 2, "input": "SECRET-PROMPT-TWO"}]'
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert cases_handler(lambda: raw)(Request("/cases", "", "1", {})) == raw
    (line,) = _lines(caplog)
    assert line.startswith("process memory point=cases_loaded ")
    assert line.endswith(" cases=2")
    assert "SECRET" not in caplog.text


def test_a_refused_selection_logs_no_memory_line(caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level(logging.INFO, logger=LOGGER),
        pytest.raises(ResolutionError),
    ):
        cases_handler(lambda: "[]")(Request("/cases", "", "1", {}))
    assert _lines(caplog) == []
