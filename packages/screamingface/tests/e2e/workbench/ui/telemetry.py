"""Load a bundle's telemetry and shape it for the bundle page (unit 6 plan, Task 5). Pure.

``load(directory)`` reads what the run wrote (spec §3.6): ``events.jsonl`` (SDK events),
``spans.jsonl`` (the OTLP spans of the run's trace ids), ``report.json``, ``accounting.json``
and ``telemetry.json`` (what was dropped, and why a file is empty). The view models below it
(``waterfall``, ``usage_by_model``, ``log_entries``, ``cases``) are pure functions of that data.

Bundles may come from an unzipped CI artifact, so every file is untrusted:
- symlinks are never followed, and each file is read up to a byte cap;
- at most ``LINES_CAP`` lines per JSONL file are kept; the rest are counted (``over_cap``), and a
  line that is not a JSON object (or the torn, newline-less tail of a killed writer) is skipped
  and counted (``unreadable``). Nothing is dropped silently;
- everything is redacted AGAIN on load (``workbench.redaction``): a bundle written before
  redaction existed, or by hand, must not put a key on the page (Review Focus 2);
- every field is read defensively: a wrong type reads as unknown (``None``), never raises.

INVARIANT: unknown is ``None``, never 0. A sum with one unknown part is unknown.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from workbench.bundle import EVENTS_FILE, SPANS_FILE, TELEMETRY_FILE
from workbench.redaction import redact_named_tree
from workbench.telemetry_recorder import ACCOUNTING_FILE, REPORT_FILE
from workbench.ui.bundles import regular_file

LINES_CAP: Final = 20_000  # the writers' own cap (EVENTS_CAP, SPANS_CAP)
JSONL_BYTES_CAP: Final = 64 << 20
JSON_BYTES_CAP: Final = 16 << 20
FOLD_AT: Final = 10  # more same-named siblings than this fold into one row ...
FOLD_KEEP: Final = 3  # ... after the first FOLD_KEEP of them
SEVERITIES: Final = ("DEBUG", "INFO", "WARN", "ERROR")

type Json = dict[str, Any]


# --- loader ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Dropped:
    events: int | None = None  # the recorder's cap (telemetry.json); None when unknown
    events_failed: int | None = None  # events the recorder could not write
    spans: int | None = None  # spans beyond the bundle writer's cap
    unreadable: int = 0  # lines this loader could not parse
    over_cap: int = 0  # lines beyond this loader's cap or byte cap


@dataclass(frozen=True)
class Telemetry:
    events: tuple[Json, ...] = ()
    spans: tuple[Json, ...] = ()
    report: Json | None = None
    accounting: Json | None = None
    dropped: Dropped = Dropped()
    notes: tuple[str, ...] = ()  # why something is missing, in the writer's words

    @property
    def present(self) -> bool:
        parts = (self.events, self.spans, self.report, self.accounting, self.notes)
        return any(parts) or self.dropped != Dropped()


def _read(path: Path, cap: int) -> tuple[bytes, bool] | None:
    """The file's first ``cap`` bytes and whether it had more; None when absent or unsafe."""
    if not regular_file(path):
        return None
    try:
        with path.open("rb") as handle:
            data = handle.read(cap + 1)
    except OSError:
        return None
    return data[:cap], len(data) > cap


def _object(text: bytes | str) -> Json | None:
    try:
        value: object = json.loads(text)
    except ValueError:
        return None
    return redact_named_tree(value) if isinstance(value, dict) else None


def _json_file(path: Path) -> Json | None:
    read = _read(path, JSON_BYTES_CAP)
    return None if read is None or read[1] else _object(read[0])


@dataclass
class _Lines:
    rows: list[Json]
    unreadable: int = 0
    over_cap: int = 0


def _jsonl(path: Path, cap: int) -> _Lines:
    out = _Lines([])
    read = _read(path, JSONL_BYTES_CAP)
    if read is None:
        return out
    data, truncated = read
    *whole, tail = data.split(b"\n")
    out.over_cap += 1 if truncated else 0  # the bytes past the cap hold at least one line
    out.unreadable += 1 if tail.strip() and not truncated else 0  # a torn last line
    for line in (raw for raw in whole if raw.strip()):
        if len(out.rows) >= cap:
            out.over_cap += 1
            continue
        row = _object(line)
        if row is None:
            out.unreadable += 1
        else:
            out.rows.append(row)
    return out


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dict(value: object) -> Json:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]


def dicts(value: object) -> list[Json]:
    """The dict items of ``value`` when it is a list; anything else is no items."""
    return [item for item in _list(value) if isinstance(item, dict)]


def _notes(summary: Json) -> tuple[str, ...]:
    notes = [_str(_dict(summary.get(part)).get("note")) for part in ("events", "spans")]
    files = _dict(summary.get("files"))
    notes += [f"{name}: {state}" for name, state in files.items() if state != "written"]
    return tuple(n for n in notes if n)


def load(directory: Path, *, cap: int = LINES_CAP) -> Telemetry:
    """Everything telemetry in the bundle at ``directory``; empty when it holds none."""
    events = _jsonl(directory / EVENTS_FILE, cap)
    spans = _jsonl(directory / SPANS_FILE, cap)
    summary = _json_file(directory / TELEMETRY_FILE) or {}
    recorded, copied = _dict(summary.get("events")), _dict(summary.get("spans"))
    dropped = Dropped(
        events=int_or_none(recorded.get("dropped")),
        events_failed=int_or_none(recorded.get("failed")),
        spans=int_or_none(copied.get("dropped")),
        unreadable=events.unreadable + spans.unreadable,
        over_cap=events.over_cap + spans.over_cap,
    )
    return Telemetry(
        events=tuple(events.rows),
        spans=tuple(spans.rows),
        report=_json_file(directory / REPORT_FILE),
        accounting=_json_file(directory / ACCOUNTING_FILE),
        dropped=dropped,
        notes=_notes(summary),
    )


# --- waterfall ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpanRow:
    service: str
    depth: int
    name: str
    start_ns: int | None
    end_ns: int | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache: str | None
    error: str | None  # the failure, or for a fold "k of n failed"; None when none
    folded: int = 1  # how many sibling spans this row stands for
    hidden: int = 0  # descendants of folded spans, not shown

    @property
    def duration_ns(self) -> int | None:
        if self.start_ns is None or self.end_ns is None:
            return None
        return max(0, self.end_ns - self.start_ns)


@dataclass(frozen=True)
class Waterfall:
    rows: tuple[SpanRow, ...]
    start_ns: int | None  # the time axis, shared by every service
    end_ns: int | None


def _span_error(span: Json, attributes: Json) -> str | None:
    status = _dict(span.get("status"))
    if status.get("code") == "error":
        return _str(status.get("message")) or _str(attributes.get("error.type")) or "error"
    return _str(attributes.get("error.type"))


def _row(span: Json, service: str, depth: int) -> SpanRow:
    attributes = _dict(span.get("attributes"))
    model = attributes.get("gen_ai.response.model") or attributes.get("gen_ai.request.model")
    name = span.get("name")
    return SpanRow(
        service=service,
        depth=depth,
        name=name if isinstance(name, str) else "?",
        start_ns=int_or_none(span.get("start_ns")),
        end_ns=int_or_none(span.get("end_ns")),
        model=_str(model),
        input_tokens=int_or_none(attributes.get("gen_ai.usage.input_tokens")),
        output_tokens=int_or_none(attributes.get("gen_ai.usage.output_tokens")),
        cache=_str(attributes.get("url4.cache_status")),
        error=_span_error(span, attributes),
    )


def _sum(values: Iterable[int | None]) -> int | None:
    total = 0
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _fold(rows: Sequence[SpanRow], hidden: int) -> SpanRow:
    starts = [r.start_ns for r in rows if r.start_ns is not None]
    ends = [r.end_ns for r in rows if r.end_ns is not None]
    failed = sum(r.error is not None for r in rows)
    return SpanRow(
        service=rows[0].service,
        depth=rows[0].depth,
        name=rows[0].name,
        start_ns=min(starts) if starts else None,
        end_ns=max(ends) if ends else None,
        model=rows[0].model if len({r.model for r in rows}) == 1 else None,
        input_tokens=_sum(r.input_tokens for r in rows),
        output_tokens=_sum(r.output_tokens for r in rows),
        cache=None,
        error=f"{failed} of {len(rows)} failed" if failed else None,
        folded=len(rows),
        hidden=hidden,
    )


def _start_key(span: Json) -> tuple[int, str]:
    return (int_or_none(span.get("start_ns")) or 0, str(span.get("span_id")))


def _service(span: Json) -> str:
    return _str(span.get("service")) or "unknown service"


type _Item = tuple[Json, int] | SpanRow  # a span still to expand at a depth, or a ready fold


class _Forest:
    """One service's spans as a forest: a span whose parent is elsewhere is a root here.

    Flattened depth first with an explicit stack (no recursion: a span tree is untrusted and
    may be deep). A parent cycle has no root; its spans are emitted afterwards, never lost.
    """

    def __init__(self, service: str, spans: Sequence[Json], *, unfold: bool) -> None:
        self.service = service
        self.unfold = unfold
        self.spans = sorted(spans, key=_start_key)
        ids = {str(s.get("span_id")) for s in spans}
        self.children: dict[str, list[Json]] = {}
        self.roots: list[Json] = []
        for s in self.spans:
            parent, own = str(s.get("parent_span_id")), str(s.get("span_id"))
            if parent in ids and parent != own:
                self.children.setdefault(parent, []).append(s)
            else:
                self.roots.append(s)
        self.seen: set[int] = set()

    def _kids(self, span: Json) -> list[Json]:
        kids = self.children.get(str(span.get("span_id")), [])
        return [k for k in kids if id(k) not in self.seen]

    def _hide(self, spans: Sequence[Json]) -> int:
        """Mark ``spans`` and their subtrees shown-by-a-fold; return how many descendants."""
        hidden, stack = 0, list(spans)
        while stack:
            node = stack.pop()
            if id(node) in self.seen:
                continue
            self.seen.add(id(node))
            kids = self._kids(node)
            hidden += len(kids)
            stack.extend(kids)
        return hidden

    def _folds(self, spans: Sequence[Json]) -> dict[object, list[Json]]:
        """Per over-``FOLD_AT`` name, the siblings past the first ``FOLD_KEEP`` (none: unfold)."""
        by_name: dict[object, list[Json]] = {}
        for s in spans:
            by_name.setdefault(s.get("name"), []).append(s)
        if self.unfold:
            return {}
        return {n: group[FOLD_KEEP:] for n, group in by_name.items() if len(group) > FOLD_AT}

    def _level(self, spans: Sequence[Json], depth: int) -> list[_Item]:
        """Siblings in start order; a fold row stands where its first folded span would."""
        folds = self._folds(spans)
        firsts = {id(group[0]): group for group in folds.values()}
        folded = {id(s) for group in folds.values() for s in group}
        items: list[_Item] = []
        for s in spans:
            group = firsts.get(id(s))
            if group is not None:
                rows = [_row(x, self.service, depth) for x in group]
                items.append(_fold(rows, self._hide(group)))
            elif id(s) not in folded:
                items.append((s, depth))
        return items

    def rows(self) -> list[SpanRow]:
        out: list[SpanRow] = []
        self._flatten(self.roots, out)
        for span in self.spans:  # in start order; only a parent cycle is still unseen here
            if id(span) not in self.seen:
                self._flatten([span], out)
        return out

    def _flatten(self, roots: Sequence[Json], out: list[SpanRow]) -> None:
        stack = list(reversed(self._level(roots, 0)))
        while stack:
            item = stack.pop()
            if isinstance(item, SpanRow):
                out.append(item)
                continue
            span, depth = item
            if id(span) in self.seen:
                continue
            self.seen.add(id(span))
            out.append(_row(span, self.service, depth))
            stack.extend(reversed(self._level(self._kids(span), depth + 1)))


def waterfall(spans: Sequence[Json], *, unfold: bool = False) -> Waterfall:
    """The spans as waterfall rows, grouped by service (sorted by name), each a forest."""
    by_service: dict[str, list[Json]] = {}
    for span in spans:
        by_service.setdefault(_service(span), []).append(span)
    rows = [
        row
        for service in sorted(by_service)
        for row in _Forest(service, by_service[service], unfold=unfold).rows()
    ]
    starts = [s for s in (int_or_none(x.get("start_ns")) for x in spans) if s is not None]
    ends = [e for e in (int_or_none(x.get("end_ns")) for x in spans) if e is not None]
    return Waterfall(tuple(rows), min(starts, default=None), max(ends, default=None))


def page_of[T](rows: Sequence[T], page: int, size: int) -> tuple[Sequence[T], int, int]:
    """Rows of the 1-based ``page`` (clamped into range), that page, and the page count."""
    pages = max(1, -(-len(rows) // size))
    page = min(max(page, 1), pages)
    return rows[(page - 1) * size : page * size], page, pages


# --- usage, accounting, logs, cases ---------------------------------------------------------


def money(value: object) -> Decimal | None:
    """A USD amount (a decimal string, as the writers emit it); None when unknown/malformed."""
    if not isinstance(value, str):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def money_sum(values: Iterable[Decimal | None]) -> Decimal | None:
    total = Decimal(0)
    for value in values:
        if value is None:
            return None
        total += value
    return total


@dataclass(frozen=True)
class ModelUsage:
    model: str
    calls: int
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None


def usage_by_model(events: Sequence[Json]) -> list[ModelUsage]:
    """The SDK ``usage`` events of scope ``self`` (a ``subtree`` roll-up would double count),
    summed per model; one unknown part makes that model's total unknown."""
    groups: dict[str, list[Json]] = {}
    for event in events:
        if event.get("kind") == "usage" and event.get("scope") == "self":
            groups.setdefault(_str(event.get("model")) or "unknown model", []).append(event)
    rows: list[ModelUsage] = []
    for model, group in sorted(groups.items()):
        usages = [_dict(e.get("usage")) for e in group]
        rows.append(
            ModelUsage(
                model=model,
                calls=len(group),
                input_tokens=_sum(int_or_none(u.get("input_tokens")) for u in usages),
                output_tokens=_sum(int_or_none(u.get("output_tokens")) for u in usages),
                cost_usd=money_sum(money(u.get("cost_usd")) for u in usages),
            )
        )
    return rows


@dataclass(frozen=True)
class LogEntry:
    sequence: int | None
    timestamp: str
    severity: str  # one of SEVERITIES, or "unknown"
    body: str
    attributes: Json


def _termination(event: Json) -> LogEntry | None:
    status = _str(event.get("status")) or "unknown"
    if status == "succeeded":
        return None
    error = _dict(event.get("error"))
    detail = ": ".join(t for t in (_str(error.get("code")), _str(error.get("message"))) if t)
    body = f"terminated {status}" + (f": {detail}" if detail else "")
    return LogEntry(int_or_none(event.get("sequence")), _str(event.get("timestamp")) or "", "ERROR",
                    body, {})  # fmt: skip


def _log(event: Json) -> LogEntry:
    severity = event.get("severity_text")
    return LogEntry(
        sequence=int_or_none(event.get("sequence")),
        timestamp=_str(event.get("timestamp")) or "",
        severity=severity if isinstance(severity, str) and severity in SEVERITIES else "unknown",
        body=_str(event.get("body")) or "",
        attributes=_dict(event.get("attributes")),
    )


def log_entries(events: Sequence[Json]) -> list[LogEntry]:
    """The SDK ``log`` events, plus a failed run's termination (with its error) as an ERROR."""
    entries: list[LogEntry] = []
    for event in events:
        kind = event.get("kind")
        entry = _log(event) if kind == "log" else None
        entry = _termination(event) if kind == "terminated" else entry
        if entry is not None:
            entries.append(entry)
    return entries


@dataclass(frozen=True)
class CaseRow:
    candidate: str
    case_id: str
    status: str | None
    score: float | None
    stop_reason: str | None
    finish_reason: str | None
    rounds: int | None
    failures: int | None


def _score(grade: object) -> float | None:
    score = _dict(grade).get("score")
    return float(score) if isinstance(score, int | float) and not isinstance(score, bool) else None


def _case(candidate: str, case: Json) -> CaseRow:
    failures = case.get("failures")
    case_id = case.get("case_id")
    return CaseRow(
        candidate=candidate,
        case_id="unknown" if case_id is None else str(case_id),
        status=_str(case.get("status")),
        score=_score(case.get("grade")),
        stop_reason=_str(case.get("stop_reason")),
        finish_reason=_str(case.get("finish_reason")),
        rounds=int_or_none(case.get("rounds_executed")),
        failures=len(failures) if isinstance(failures, list) else None,  # pyright: ignore[reportUnknownArgumentType]
    )


def cases(report: Json | None) -> list[CaseRow]:
    """Every case of every candidate in ``report.json``; malformed entries are skipped."""
    rows: list[CaseRow] = []
    for c in dicts(_dict(report).get("candidates")):
        name = _str(c.get("name")) or "unknown"
        rows += [_case(name, case) for case in dicts(c.get("cases"))]
    return rows
