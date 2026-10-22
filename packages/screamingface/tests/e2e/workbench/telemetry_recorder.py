"""The quickstart notebook's SDK telemetry recorder (spec §3.6; unit 6 plan, Task 4).

Imported INSIDE the notebook kernel (the workbench kernelspec puts ``tests/e2e`` on its
``PYTHONPATH``), only when the workbench sets ``EVENTS_PATH``. A notebook run outside the
workbench never imports it.

- ``EventRecorder(path)`` is the ``on_event`` callback: each SDK event (``Started``, ``Span``,
  ``Usage``, ``Log``, ``Terminated``) becomes one JSON line in ``events.jsonl``.
- ``EventRecorder.finish(report)`` (the result cell) writes ``report.json``
  (``Report.to_dict()``), ``accounting.json`` (each candidate's accounting by model and by
  stage) and ``recorder.json`` (counts and per-file outcome) beside it.

INVARIANT: redaction before disk. Every value goes through ``workbench.redaction`` (the one
redactor, applied to values — never to serialised JSON) before it is written, and the value
of a secret-NAMED key (a ``Log`` attribute ``…x-api-key``, a container under ``auth``) is
masked whole.

INVARIANT: the recorder never raises into the SDK. An ``on_event`` that raised would abort the
evaluation it only observes; a failure is counted (``failed``) and the run goes on.

INVARIANT: whole lines only. Each event is ONE ``write`` of a newline-terminated line under a
lock, then a flush, so a live tail (Task 6) that reads complete lines never sees half an event.

INVARIANT: bounded. At most ``EVENTS_CAP`` lines; later events are counted as ``dropped`` and
reported, never silently truncated.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import math
import threading
from collections.abc import Callable, Mapping, Set
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import IO, Any, Final

from workbench.redaction import redact, redact_named_tree

EVENTS_CAP: Final = 20_000
REPORT_FILE: Final = "report.json"
ACCOUNTING_FILE: Final = "accounting.json"
RECORDER_FILE: Final = "recorder.json"
ACCOUNTING_SCHEMA: Final = "workbench.accounting.v1"


def _number(value: float | Decimal) -> Any:
    """A finite number as JSON; NaN/inf as text, so every line is strict JSON."""
    if isinstance(value, Decimal):
        return str(value)  # exact: a float would round money
    return value if math.isfinite(value) else str(value)


def _fields(value: Any) -> dict[str, Any]:
    # A private slot (`Log._attributes`) is exposed by a public property of the same name.
    return {
        f.name.lstrip("_"): to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)
    }


def _mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(k): to_jsonable(v) for k, v in value.items()}


def _sequence(value: Any) -> list[Any]:
    ordered: Any = sorted(value, key=str) if isinstance(value, Set) else value  # pyright: ignore[reportUnknownArgumentType]
    return [to_jsonable(v) for v in ordered]


def _is_instance(value: Any) -> bool:
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


# First match wins; anything else is rendered with `str`.
_CONVERTERS: Final[tuple[tuple[Callable[[Any], bool], Callable[[Any], Any]], ...]] = (
    (lambda v: isinstance(v, float | Decimal), _number),
    (lambda v: isinstance(v, datetime | date | time), lambda v: v.isoformat()),
    (lambda v: isinstance(v, enum.Enum), lambda v: to_jsonable(v.value)),
    (_is_instance, _fields),
    (lambda v: isinstance(v, Mapping), _mapping),
    (lambda v: isinstance(v, list | tuple | Set), _sequence),
)


def to_jsonable(value: Any) -> Any:
    """``value`` as a JSON-ready tree: dataclasses (slots included) as dicts, ``Decimal`` as an
    exact string, ``datetime`` as ISO 8601, enums by value, mappings with string keys,
    sequences and sets as lists. ``None`` stays ``None`` (unknown is never zero)."""
    if value is None or isinstance(value, str | bool | int):
        return value
    convert = next((c for matches, c in _CONVERTERS if matches(value)), str)
    return convert(value)


def event_json(event: Any) -> dict[str, Any]:
    """One SDK event as a redacted JSON-ready dict, ``kind`` first."""
    return redact_named_tree({"kind": event.kind} | _fields(event))


def _summary_rows(label: str, groups: Mapping[Any, Any]) -> list[dict[str, Any]]:
    # WHY a list, not a dict keyed by model: the anonymous bucket's key is None, and a JSON
    # object key cannot keep None apart from the string "None".
    return [{label: key} | to_jsonable(summary) for key, summary in groups.items()]


def _accounting(report: Any) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for candidate in report.candidates:
        breakdown = candidate.accounting
        candidates.append(
            {
                "name": candidate.name,
                "run_id": to_jsonable(candidate.run_id),
                "unattributed_cost_usd": to_jsonable(breakdown.unattributed_cost_usd),
                "consistent": breakdown.consistent,
                "by_model": _summary_rows("model", breakdown.by_model),
                "by_stage": _summary_rows("stage", breakdown.by_stage),
                "rows": to_jsonable(breakdown.rows),
            }
        )
    return {"schema": ACCOUNTING_SCHEMA, "candidates": candidates}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(redact_named_tree(value), indent=2, allow_nan=False) + "\n", "utf-8")


class EventRecorder:
    """``on_event`` callback appending each SDK event to ``path`` as one redacted JSON line."""

    def __init__(self, path: str | Path, *, cap: int = EVENTS_CAP) -> None:
        self.path = Path(path)
        self.cap = cap
        self._lock = threading.Lock()
        self._recorded = 0
        self._dropped = 0
        self._failed = 0
        self._finished = False
        self._fh: IO[str] | None
        try:
            # "w": a rerun into the same bundle never inherits the previous run's events.
            self._fh = self.path.open("w", encoding="utf-8")
        except OSError:
            self._fh = None

    def __call__(self, event: Any) -> None:
        with self._lock:
            if self._finished:
                return
            if self._recorded >= self.cap:
                self._dropped += 1
                return
            try:
                if self._fh is None:
                    raise OSError("events file could not be opened")
                line = json.dumps(event_json(event), allow_nan=False) + "\n"
                self._fh.write(line)
                self._fh.flush()
                self._recorded += 1
            except Exception:  # noqa: BLE001 — never raise into the SDK (module INVARIANT)
                self._failed += 1

    def finish(self, report: Any) -> dict[str, Any]:
        """Close the events file; write the report, its accounting and ``recorder.json``.

        Never raises: each file's outcome (``written``, ``no report``, or a redacted
        ``error: …``) is returned and recorded in ``recorder.json``.
        """
        with self._lock:
            self._finished = True
            if self._fh is not None:
                self._fh.close()
                self._fh = None
        summary: dict[str, Any] = {
            "events": {
                "recorded": self._recorded,
                "dropped": self._dropped,
                "failed": self._failed,
                "cap": self.cap,
            },
            "files": {
                REPORT_FILE: self._write(REPORT_FILE, report, lambda r: r.to_dict()),
                ACCOUNTING_FILE: self._write(ACCOUNTING_FILE, report, _accounting),
            },
        }
        try:
            _write_json(self.path.parent / RECORDER_FILE, summary)
        except Exception:  # noqa: BLE001, S110 — the summary is also returned to the caller
            pass
        return summary

    def _write(self, name: str, report: Any, build: Any) -> str:
        if report is None:
            return "no report"
        try:
            _write_json(self.path.parent / name, build(report))
        except Exception as exc:  # noqa: BLE001 — evidence, never a second failure
            return redact(f"error: {type(exc).__name__}: {exc}")
        return "written"
