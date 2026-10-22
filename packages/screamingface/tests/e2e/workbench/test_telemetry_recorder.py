"""The notebook's SDK telemetry recorder (unit 6 plan, Task 4): events, report, accounting."""

from __future__ import annotations

import dataclasses
import enum
import json
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

import screamingface as sf
from screamingface import events as ev
from workbench.redaction import MASK
from workbench.telemetry_recorder import (
    ACCOUNTING_FILE,
    EVENTS_CAP,
    RECORDER_FILE,
    REPORT_FILE,
    EventRecorder,
    to_jsonable,
)

_T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
_TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
# Fake, assembled at runtime (secret scanners).
_KEY = "sk-or-v1-" + "a1b2c3d4" * 4
_OPAQUE = "op4que-V4lue-zz9"


def _base(seq: int) -> dict[str, Any]:
    return {
        "id": f"e{seq}",
        "run_id": "run-1",
        "sequence": seq,
        "timestamp": _T0,
        "source": "engine",
        "traceparent": _TP,
    }


def _events() -> list[ev.Event]:
    return [
        ev.Started(**_base(1), url4="url4://x"),
        ev.Span(
            **_base(2),
            name="chat",
            operation="chat",
            start=_T0,
            end=_T0,
            request_model="openrouter/x/y",
            input_tokens=3,
            output_tokens=4,
            finish_reasons=("stop",),
            cache_status="hit",
            cache_saved_cost_usd=Decimal("0.0012"),
        ),
        ev.Usage(
            **_base(3),
            provider="openrouter",
            model="openrouter/x/y",
            pricing_version="v1",
            usage=sf.Usage(input_tokens=3, output_tokens=4, cost_usd=Decimal("0.5")),
        ),
        ev.Log(
            **_base(4),
            severity_number=17,
            severity_text="ERROR",
            body=f"provider said: invalid key {_KEY}",
            attributes={"http.request.header.x-api-key": _OPAQUE, "n": 1},
        ),
        ev.Terminated(
            **_base(5),
            status="failed",
            error=ev.TerminationError(code="upstream", message=f"OPENROUTER_API_KEY={_OPAQUE}"),
        ),
    ]


def _lines(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    return [json.loads(line) for line in text.splitlines()]


def test_every_event_is_one_json_line_with_its_kind_and_fields(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    for event in _events():
        recorder(event)
    rows = _lines(path)
    assert [r["kind"] for r in rows] == ["started", "span", "usage", "log", "terminated"]
    span = rows[1]
    assert span["timestamp"] == "2026-10-22T12:00:00+00:00"
    assert span["cache_saved_cost_usd"] == "0.0012"  # Decimal as an exact string
    assert span["finish_reasons"] == ["stop"]
    assert span["traceparent"] == _TP
    assert rows[2]["usage"]["cost_usd"] == "0.5"  # nested dataclass
    assert rows[2]["usage"]["cache_read_tokens"] is None  # unknown stays null, never 0
    assert rows[3]["attributes"]["n"] == 1  # the private _attributes slot reads as attributes
    assert rows[4]["error"]["code"] == "upstream"


def test_each_line_is_flushed_as_it_is_recorded(tmp_path: Path) -> None:
    """A live tail (Task 6) sees an event before the run ends, never a half line."""
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    first, second = _events()[:2]
    recorder(first)
    assert [r["kind"] for r in _lines(path)] == ["started"]
    recorder(second)
    assert len(_lines(path)) == 2


def test_secrets_in_a_log_body_attribute_or_error_never_reach_disk(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    for event in _events():
        recorder(event)
    text = path.read_text(encoding="utf-8")
    assert _KEY not in text and _OPAQUE not in text
    rows = _lines(path)
    assert rows[3]["body"] == f"provider said: invalid key {MASK}"
    assert rows[3]["attributes"]["http.request.header.x-api-key"] == MASK
    assert rows[4]["error"]["message"] == f"OPENROUTER_API_KEY={MASK}"


def test_a_new_recorder_starts_an_empty_file(tmp_path: Path) -> None:
    """A rerun into the same bundle never inherits the previous run's events."""
    path = tmp_path / "events.jsonl"
    path.write_text('{"stale": true}\n')
    EventRecorder(path)
    assert path.read_text() == ""


def test_events_past_the_cap_are_counted_never_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path, cap=2)
    for event in _events():
        recorder(event)
    assert len(_lines(path)) == 2
    summary = recorder.finish(None)
    assert summary["events"] == {"recorded": 2, "dropped": 3, "failed": 0, "cap": 2}


def test_the_default_cap_is_twenty_thousand() -> None:
    assert EVENTS_CAP == 20_000


def test_the_recorder_never_raises_into_the_sdk(tmp_path: Path) -> None:
    """An on_event that raises would abort the evaluation it is only observing."""

    class _Weird:
        kind = "weird"

        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("boom")

    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    recorder(_Weird())  # pyright: ignore[reportArgumentType]
    recorder(_events()[0])
    assert [r["kind"] for r in _lines(path)] == ["started"]
    assert recorder.finish(None)["events"]["failed"] == 1


def test_an_unwritable_path_disables_the_recorder_without_raising(tmp_path: Path) -> None:
    recorder = EventRecorder(tmp_path / "missing-dir" / "events.jsonl")
    recorder(_events()[0])
    summary = recorder.finish(None)
    assert summary["events"]["recorded"] == 0 and summary["events"]["failed"] == 1


def test_concurrent_events_never_interleave_inside_a_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    event = _events()[3]
    threads = [
        threading.Thread(target=lambda: [recorder(event) for _ in range(50)]) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_lines(path)) == 200


class _Colour(enum.Enum):
    RED = "red"


def test_to_jsonable_handles_the_sdk_value_types() -> None:
    value = {
        "d": Decimal("1.10"),
        "t": _T0,
        "e": _Colour.RED,
        "m": MappingProxyType({1: (2, 3)}),
        "s": frozenset({"x"}),
        "u": sf.Usage(cost_usd=Decimal("2")),
        "none": None,
    }
    out = to_jsonable(value)
    assert out["d"] == "1.10"
    assert out["t"] == "2026-10-22T12:00:00+00:00"
    assert out["e"] == "red"
    assert out["m"] == {"1": [2, 3]}
    assert out["s"] == ["x"]
    assert out["u"]["cost_usd"] == "2" and out["u"]["input_tokens"] is None
    assert out["none"] is None
    json.dumps(out)


# --- the result cell's files --------------------------------------------------------------


class _FakeReport:
    def __init__(self, payload: dict[str, Any], candidates: list[Any]) -> None:
        self._payload = payload
        self.candidates = candidates

    def to_dict(self) -> dict[str, Any]:
        return self._payload


class _FakeCandidate:
    def __init__(self, name: str, accounting: Any) -> None:
        self.name = name
        self.run_id = "r1"
        self._accounting = accounting

    @property
    def accounting(self) -> Any:
        if isinstance(self._accounting, BaseException):
            raise self._accounting
        return self._accounting


def _summary(cost: str | None) -> Any:
    from screamingface.accounting import AccountingSummary
    from screamingface.operation_accounting import OperationCache

    usage = sf.Usage(
        input_tokens=1, output_tokens=2, cost_usd=None if cost is None else Decimal(cost)
    )
    return AccountingSummary(usage, 1, OperationCache(1, 0, 0, 0), 10, 1)


class _FakeBreakdown:
    unattributed_cost_usd = None
    consistent = True
    rows = ()

    @property
    def by_model(self) -> Any:
        return MappingProxyType({"openrouter/x/y": _summary("0.5"), None: _summary(None)})

    @property
    def by_stage(self) -> Any:
        return MappingProxyType({"generation": _summary("0.5")})


def test_finish_writes_the_report_and_its_accounting_redacted(tmp_path: Path) -> None:
    recorder = EventRecorder(tmp_path / "events.jsonl")
    report = _FakeReport(
        {"schema": "screamingface.report.v1", "note": f"OPENROUTER_API_KEY={_OPAQUE}"},
        [_FakeCandidate("best", _FakeBreakdown())],
    )
    summary = recorder.finish(report)
    assert json.loads((tmp_path / REPORT_FILE).read_text())["note"] == f"OPENROUTER_API_KEY={MASK}"
    accounting = json.loads((tmp_path / ACCOUNTING_FILE).read_text())
    (candidate,) = accounting["candidates"]
    assert candidate["name"] == "best"
    by_model = {row["model"]: row for row in candidate["by_model"]}
    assert by_model["openrouter/x/y"]["usage"]["cost_usd"] == "0.5"
    assert by_model[None]["usage"]["cost_usd"] is None  # an anonymous bucket stays None
    assert candidate["by_stage"][0]["stage"] == "generation"
    assert summary["files"] == {REPORT_FILE: "written", ACCOUNTING_FILE: "written"}
    assert json.loads((tmp_path / RECORDER_FILE).read_text()) == summary


def test_finish_without_a_report_says_so(tmp_path: Path) -> None:
    recorder = EventRecorder(tmp_path / "events.jsonl")
    summary = recorder.finish(None)
    assert summary["files"] == {REPORT_FILE: "no report", ACCOUNTING_FILE: "no report"}
    assert not (tmp_path / REPORT_FILE).exists()


def test_a_failing_accounting_view_is_recorded_redacted_and_never_raised(tmp_path: Path) -> None:
    recorder = EventRecorder(tmp_path / "events.jsonl")
    report = _FakeReport({}, [_FakeCandidate("c", RuntimeError(f"token={_OPAQUE}"))])
    summary = recorder.finish(report)
    assert summary["files"][REPORT_FILE] == "written"
    assert summary["files"][ACCOUNTING_FILE] == f"error: RuntimeError: token={MASK}"
    assert _OPAQUE not in (tmp_path / RECORDER_FILE).read_text()


def test_finish_closes_the_file_and_later_events_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    recorder.finish(None)
    recorder(_events()[0])
    assert path.read_text() == ""


@pytest.mark.parametrize("bad", [Decimal("NaN"), float("inf")])
def test_non_finite_numbers_become_strings_so_every_line_is_strict_json(bad: Any) -> None:
    out = json.dumps(to_jsonable({"x": bad}), allow_nan=False)
    assert json.loads(out)["x"] == str(bad)


# Security review: a container under a secret-named Log attribute is masked whole, and cookies
# are secret names.
def test_a_secret_named_container_or_cookie_attribute_never_reaches_disk(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    attributes = {
        "llm.api.key": _OPAQUE,
        "http.request.header.cookie": _OPAQUE,
        "set-cookie": _OPAQUE,
        "max_tokens": 256,
        "token_count": "7",
    }
    recorder(
        ev.Log(**_base(1), severity_number=9, severity_text="INFO", body="b", attributes=attributes)
    )
    assert _OPAQUE not in path.read_text(encoding="utf-8")
    (row,) = _lines(path)
    assert row["attributes"] == {
        "llm.api.key": MASK,
        "http.request.header.cookie": MASK,
        "set-cookie": MASK,
        "max_tokens": 256,
        "token_count": "7",
    }


@dataclasses.dataclass(frozen=True)
class _Custom:
    """An event whose fields hold containers under secret names (a future SDK event shape)."""

    kind: str
    auth: dict[str, str]
    credentials: tuple[str, ...]
    usage: dict[str, int]


def test_a_container_under_a_secret_named_field_is_masked_whole(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = EventRecorder(path)
    recorder(_Custom("custom", {"value": _OPAQUE}, (_OPAQUE,), {"max_tokens": 9}))
    assert _OPAQUE not in path.read_text(encoding="utf-8")
    (row,) = _lines(path)
    assert row == {
        "kind": "custom",
        "auth": MASK,
        "credentials": MASK,
        "usage": {"max_tokens": 9},
    }
