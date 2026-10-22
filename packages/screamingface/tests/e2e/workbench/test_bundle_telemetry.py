"""Bundle-time telemetry (unit 6 plan, Task 4): the run's spans, the events summary, caps."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from workbench.bundle import (
    EVENTS_FILE,
    SPANS_CAP,
    SPANS_FILE,
    TELEMETRY_FILE,
    bundle_dir,
    prepare_bundle,
    settled,
    write_telemetry,
)
from workbench.redaction import MASK
from workbench.telemetry_recorder import ACCOUNTING_FILE, RECORDER_FILE, REPORT_FILE

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
OTHER = "00f067aa0ba902b7aaaaaaaaaaaaaaaa"
OPAQUE = "op4que-V4lue-zz9"


def _span(trace_id: str, i: int = 0, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    attributes = attributes or {}
    return {
        "trace_id": trace_id,
        "span_id": f"{i:016x}",
        "name": "url4.run",
        "attributes": attributes,
    }


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _telemetry(bundle: Path) -> dict[str, Any]:
    return json.loads((bundle / TELEMETRY_FILE).read_text())


class _Receiver:
    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self.spans = spans
        self.asked: list[list[str]] = []

    def __call__(self, trace_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(trace_ids)
        self.asked.append(ids)
        return [s for s in self.spans if s["trace_id"] in ids]


def test_bundle_dir_is_target_then_notebook(tmp_path: Path) -> None:
    assert bundle_dir(tmp_path, "replay", "quickstart") == tmp_path / "replay" / "quickstart"


def test_prepare_bundle_creates_it_and_clears_a_previous_runs_telemetry(tmp_path: Path) -> None:
    bundle = tmp_path / "replay" / "quickstart"
    bundle.mkdir(parents=True)
    stale = (EVENTS_FILE, SPANS_FILE, TELEMETRY_FILE, REPORT_FILE, ACCOUNTING_FILE, RECORDER_FILE)
    for name in stale:
        (bundle / name).write_text("stale")
    (bundle / "executed.ipynb").write_text("kept")  # rewritten by write_bundle anyway
    assert prepare_bundle(tmp_path, "replay", "quickstart") == bundle
    assert sorted(p.name for p in bundle.iterdir()) == ["executed.ipynb"]


def test_only_this_runs_trace_ids_are_copied(tmp_path: Path) -> None:
    receiver = _Receiver([_span(TID, 1), _span(OTHER, 2), _span(TID, 3)])
    write_telemetry(tmp_path, [TID], receiver)
    assert receiver.asked == [[TID]]
    assert [s["span_id"] for s in _lines(tmp_path / SPANS_FILE)] == [f"{1:016x}", f"{3:016x}"]
    spans = _telemetry(tmp_path)["spans"]
    assert spans == {"file": SPANS_FILE, "copied": 2, "dropped": 0, "cap": SPANS_CAP, "note": None}


def test_spans_are_redacted_again_before_they_land(tmp_path: Path) -> None:
    attrs = {"http.request.header.x-api-key": OPAQUE, "msg": f"token={OPAQUE}"}
    write_telemetry(tmp_path, [TID], _Receiver([_span(TID, attributes=attrs)]))
    assert OPAQUE not in (tmp_path / SPANS_FILE).read_text()
    (span,) = _lines(tmp_path / SPANS_FILE)
    assert span["attributes"]["http.request.header.x-api-key"] == MASK


def test_spans_past_the_cap_are_counted_and_shown(tmp_path: Path) -> None:
    receiver = _Receiver([_span(TID, i) for i in range(5)])
    write_telemetry(tmp_path, [TID], receiver, cap=3)
    assert len(_lines(tmp_path / SPANS_FILE)) == 3
    spans = _telemetry(tmp_path)["spans"]
    assert (spans["copied"], spans["dropped"], spans["cap"]) == (3, 2, 3)


def test_the_default_span_cap_is_twenty_thousand() -> None:
    assert SPANS_CAP == 20_000


@pytest.mark.parametrize(
    ("trace_ids", "receiver", "note"),
    [
        ([TID], _Receiver([_span(OTHER)]), "no spans received for this run's trace ids"),
        ([], _Receiver([_span(TID)]), "no trace ids to select spans by"),
        ([TID], None, "no OTLP receiver in this session"),
    ],
    ids=["none-received", "no-trace-ids", "no-receiver"],
)
def test_an_empty_span_file_says_why(
    tmp_path: Path, trace_ids: list[str], receiver: Any, note: str
) -> None:
    write_telemetry(tmp_path, trace_ids, receiver)
    assert (tmp_path / SPANS_FILE).read_text() == ""
    spans = _telemetry(tmp_path)["spans"]
    assert spans["copied"] == 0 and spans["note"] == note


def test_a_failing_receiver_never_fails_the_bundle_and_is_redacted(tmp_path: Path) -> None:
    def broken(_: Iterable[str]) -> list[dict[str, Any]]:
        raise ValueError(f"bad line api_key={OPAQUE}")

    write_telemetry(tmp_path, [TID], broken)
    spans = _telemetry(tmp_path)["spans"]
    assert spans["copied"] == 0
    assert spans["note"] == f"spans unavailable: ValueError: bad line api_key={MASK}"


def test_the_events_summary_comes_from_the_recorder(tmp_path: Path) -> None:
    (tmp_path / EVENTS_FILE).write_text('{"kind": "log"}\n')
    recorder = {
        "events": {"recorded": 1, "dropped": 4, "failed": 0, "cap": 20_000},
        "files": {REPORT_FILE: "written", ACCOUNTING_FILE: "no report"},
    }
    (tmp_path / RECORDER_FILE).write_text(json.dumps(recorder))
    write_telemetry(tmp_path, [TID], _Receiver([]))
    telemetry = _telemetry(tmp_path)
    assert telemetry["events"] == {"file": EVENTS_FILE, **recorder["events"], "note": None}
    assert telemetry["files"] == recorder["files"]


def test_events_of_a_recorder_that_never_finished_are_counted_from_the_file(
    tmp_path: Path,
) -> None:
    # The notebook died before its result cell: whole lines count, a torn tail does not.
    (tmp_path / EVENTS_FILE).write_text('{"kind": "log"}\n{"kind": "span"}\n{"kind": "sp')
    write_telemetry(tmp_path, [TID], _Receiver([]))
    events = _telemetry(tmp_path)["events"]
    assert (events["recorded"], events["dropped"], events["failed"]) == (2, None, None)
    assert (
        events["note"] == "the recorder did not finish: the notebook stopped before its result cell"
    )


def test_no_events_file_says_the_recorder_never_started(tmp_path: Path) -> None:
    write_telemetry(tmp_path, [TID], _Receiver([]))
    events = _telemetry(tmp_path)["events"]
    assert events["recorded"] == 0
    assert events["note"] == "no events recorded: the notebook never started its recorder"


def test_a_torn_recorder_summary_falls_back_to_the_events_file(tmp_path: Path) -> None:
    (tmp_path / EVENTS_FILE).write_text('{"kind": "log"}\n')
    (tmp_path / RECORDER_FILE).write_text('{"events": {"recor')
    write_telemetry(tmp_path, [TID], _Receiver([]))
    events = _telemetry(tmp_path)["events"]
    assert events["recorded"] == 1 and events["dropped"] is None


# The services batch their spans, so the last batch can land just after the notebook ends: the
# verdict waits until the run's span count has been still for a quiet window, bounded.


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _Arriving:
    """``spans_for`` whose answer grows by one span on each of the first ``grow`` calls."""

    def __init__(self, grow: int) -> None:
        self.calls = 0
        self.grow = grow

    def __call__(self, trace_ids: Iterable[str]) -> list[dict[str, Any]]:
        self.calls += 1
        return [_span(TID, i) for i in range(min(self.calls, self.grow))]


def test_settled_waits_for_late_spans_then_a_quiet_window() -> None:
    clock, source = _Clock(), _Arriving(grow=3)
    spans = settled(source, quiet_s=1.0, max_s=10.0, poll_s=0.25, clock=clock, sleep=clock.sleep)(
        [TID]
    )
    assert len(spans) == 3
    assert clock.now == pytest.approx(0.5 + 1.0)  # grew until t=0.5, then 1 s still


def test_settled_is_bounded_when_spans_keep_arriving() -> None:
    clock, source = _Clock(), _Arriving(grow=10_000)
    spans = settled(source, quiet_s=1.0, max_s=3.0, poll_s=0.25, clock=clock, sleep=clock.sleep)(
        [TID]
    )
    assert clock.now == pytest.approx(3.0)
    assert len(spans) == source.calls


def test_settled_with_nothing_arriving_costs_one_quiet_window() -> None:
    clock, source = _Clock(), _Arriving(grow=0)
    assert (
        settled(source, quiet_s=1.0, max_s=10.0, poll_s=0.25, clock=clock, sleep=clock.sleep)([TID])
        == []
    )
    assert clock.now == pytest.approx(1.0)
