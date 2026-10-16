"""Progress for a community-cache pull (epic OME-1311, spec decision 14).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: the switch follows `evaluate` — quiet when piped unless forced, on in a notebook or a
terminal; a terminal line carries rows against the total, rows added, bytes and an ETA, and is
rewritten in place; a non-interactive stream gets one line per tenth of the pull; the final line
says what finished or why the pull stopped; and a notebook gets one card updated in place.
"""

from __future__ import annotations

import io
import sys
from types import ModuleType
from typing import Any

import pytest

from screamingface._cache import progress as progress_module
from screamingface._cache.progress import Snapshot, reporter
from screamingface.cache import PullResult


class _Stream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _snapshot(
    rows: int, *, total: int | None = 1000, added: int = 0, elapsed: float = 10.0
) -> Snapshot:
    return Snapshot(
        origin="https://engine.test",
        rows_read=rows,
        rows_added=added,
        total=total,
        bytes_received=2_500_000,
        elapsed_s=elapsed,
    )


@pytest.fixture(autouse=True)
def _not_a_notebook(monkeypatch: pytest.MonkeyPatch) -> None:
    import screamingface._environment as environment

    monkeypatch.setattr(environment, "ipykernel_loaded", lambda: False)


def test_quiet_when_piped_unless_forced() -> None:
    piped = _Stream(tty=False)

    reporter(None, stream=piped).update(_snapshot(500))
    reporter(False, stream=_Stream(tty=True)).update(_snapshot(500))

    assert piped.getvalue() == ""


def test_a_terminal_line_is_rewritten_in_place_with_rows_added_bytes_and_eta() -> None:
    stream = _Stream(tty=True)
    report = reporter(None, stream=stream)

    report.preparing("https://engine.test")
    report.update(_snapshot(250, added=200))
    report.update(_snapshot(500, added=450))

    text = stream.getvalue()
    assert text.startswith("\rcommunity cache  preparing to pull from https://engine.test")
    assert "\n" not in text
    last = text.rsplit("\r", 1)[-1]
    assert "50%" in last
    assert "500/1,000 rows" in last
    assert "450 added" in last
    assert "2 MB" in last
    assert "ETA 10s" in last


def test_the_final_line_ends_the_rewritten_line() -> None:
    stream = _Stream(tty=True)
    report = reporter(None, stream=stream)

    report.update(_snapshot(900))
    report.finished(_snapshot(1000, elapsed=75.0), PullResult(1000, 640, 3, False, True))

    final = stream.getvalue().rsplit("\r", 1)[-1]
    # The final line is padded to cover the longer line it rewrites, then ends the line.
    assert final.endswith("\n")
    assert final.rstrip() == "community cache  ✓ 1,000 rows read · 640 added · 2 MB · 1m15s"


def test_a_forced_non_interactive_stream_gets_a_line_per_tenth() -> None:
    stream = _Stream(tty=False)
    report = reporter(True, stream=stream)

    for rows in (50, 90, 120, 150, 450, 460):
        report.update(_snapshot(rows))

    lines = stream.getvalue().splitlines()
    # 50, 120 and 450 rows cross into the 0th, 1st and 4th tenth; 90, 150 and 460 do not.
    assert [line.split(" · ")[0].split()[-1] for line in lines] == ["5%", "12%", "45%"]


def test_a_stopped_pull_says_how_far_it_got_and_why() -> None:
    stream = _Stream(tty=False)

    reporter(True, stream=stream).stopped(_snapshot(300, added=120), "the Engine stopped answering")

    assert stream.getvalue() == (
        "community cache  stopped after 300 rows (120 added): the Engine stopped answering\n"
    )


def test_without_a_total_the_line_shows_rows_and_no_bar() -> None:
    stream = _Stream(tty=True)

    reporter(None, stream=stream).update(_snapshot(12_345, total=None, elapsed=0.0))

    last = stream.getvalue().rsplit("\r", 1)[-1]
    assert "12,345 rows" in last
    assert "%" not in last
    assert "ETA" not in last


def test_a_notebook_gets_one_card_updated_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    import screamingface._environment as environment

    shown: list[str] = []

    class _Handle:
        def update(self, value: Any) -> None:
            shown.append(value.data)

    display = ModuleType("IPython.display")
    display.HTML = type("HTML", (), {"__init__": lambda self, data: setattr(self, "data", data)})  # type: ignore[attr-defined]
    display.display = lambda value, display_id: (shown.append(value.data), _Handle())[1]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "IPython.display", display)
    monkeypatch.setattr(environment, "ipykernel_loaded", lambda: True)

    report = reporter(None, stream=_Stream(tty=False))
    report.preparing("https://engine.test")
    report.update(_snapshot(500))
    report.finished(_snapshot(1000), PullResult(1000, 10, 1, False, True))
    report.stopped(_snapshot(1000), "<interrupted>")

    assert "preparing" in shown[0]
    assert "500/1,000 rows" in shown[2]
    assert "width:50.0%" in shown[2]
    assert "✓ 1,000 rows read" in shown[3]
    assert "&lt;interrupted&gt;" in shown[4]
    assert "pull_from_remote()" in shown[4]


def test_a_notebook_without_ipython_falls_back_to_the_terminal_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import screamingface._environment as environment

    monkeypatch.setattr(environment, "ipykernel_loaded", lambda: True)
    monkeypatch.setitem(sys.modules, "IPython.display", None)
    stream = _Stream(tty=False)

    reporter(None, stream=stream).stopped(_snapshot(1), "x")

    assert stream.getvalue().startswith("community cache  stopped")


def test_sizes_and_durations_read_naturally() -> None:
    assert progress_module._megabytes(512_000) == "512 kB"
    assert progress_module._megabytes(42_000_000) == "42 MB"
    assert progress_module._duration(9.7) == "9s"
    assert progress_module._duration(125) == "2m05s"
