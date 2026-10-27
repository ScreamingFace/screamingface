"""One model of a run across every hop, for the bundle page's Trace view (spec §3.8; u8 Task 2).

``build(bundle_dir)`` reads what the workbench already wrote — ``trace.json`` (the verdict's
hop evidence), ``spans.jsonl``, ``events.jsonl``, ``accounting.json``, ``recorder.json`` and
``logs/aigateway.txt`` — and returns a ``TraceStory``: a header (trace ids, verdict, wall time),
the hop path notebook → engine → aigateway → provider → scoreboard, one span tree across
services, one ``Call`` per gateway chat completion with its log lines, and the verdict's
checks in plain words. Pure: it reads the bundle and writes nothing.

WHY a derived client span: the SDK's evaluate call exports no span, yet its ``traceparent``
span id is the parent of ``url4.run``. When exactly one span's parent lies outside the bundle
and that span is ``url4.run``, a synthetic ``sdk.evaluate`` root takes that id, with the bounds
the recorder stamped (``first_event_ns`` / ``last_event_ns``). It is marked ``synthetic`` and
never written back. Any other shape (no orphan, several, or an orphan that is not ``url4.run``:
a cancelled run, two evaluates) gets no invented span — a note says why.

WHY log lines join by time: gateway spans carry no ``gateway_call_id`` yet (follow-up B8), so a
gateway log line of this trace (the exact ``trace_id=`` token rule, via
``telemetry.gateway_calls``) is joined to the chat-completion span whose window holds its
leading ISO-8601 timestamp. A line inside two windows goes under both, as ``time-ambiguous``;
a line without a timestamp, or outside every window, is counted in a note, never guessed.
A span that does name its ``gateway_call_id`` joins by that id instead. Only lines that carry a
``gateway_call_id`` take part (``gateway_calls`` drops the rest; ``trace.json`` counts those as
``unattributed_gateway_lines``). Windows are sorted by start and found by bisection, and the
time-matched placements are capped (``TIME_MATCH_CAP``): overlapping windows copy one line into
every call they hold, so a hostile bundle could otherwise multiply a 1 MiB log by 2 000 calls.

WHY the engine hop is the exact service name: the workbench starts the engine with
``OTEL_SERVICE_NAME=screamingface-engine`` (``targets.py``); a substring would let any other
service whose name merely contains "engine" pass for it.

INVARIANTS:
- bundle files are untrusted: ``telemetry.load`` caps, skips and redacts them; every field here
  reads defensively, and a wrong type is unknown (``None``), never 0;
- the tree is built without recursion over untrusted depth: an iterative walk visits each span
  once (a ``seen`` set), so a parent cycle or a self-parent terminates; its member becomes a
  root, with a note;
- anything cut is counted (``cut``) and anything not shown is said (``notes``);
- spend is per call only when one call used that model; a model total is never split by guess.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

from workbench.bundle import EVENTS_FILE, SPANS_FILE
from workbench.redaction import redact_named_tree
from workbench.telemetry_recorder import RECORDER_FILE
from workbench.ui import telemetry as tm
from workbench.ui.bundles import LOG_CAP_BYTES, regular_file

TRACE_FILE: Final = "trace.json"
GATEWAY_LOG: Final = Path("logs") / "aigateway.txt"
CALLS_CAP: Final = 2_000
TIME_MATCH_CAP: Final = 20_000  # time-matched log placements kept per story; the rest counted
COLLAPSE_AT: Final = 5  # this many same-named sibling leaves fold into one row ("×n")
CLIENT_SPAN: Final = "sdk.evaluate"
RUN_SPAN: Final = "url4.run"
CHAT_SPAN: Final = "POST /v1/chat/completions"
_GATEWAY_SERVICE: Final = "aigateway"
_ENGINE_SERVICE: Final = "screamingface-engine"
_REASON_CAP: Final = 200  # a hop's reason is one line, never a whole traceback
_NO_PARENT: Final = frozenset({"", "0" * 16})
_TRACE_ID: Final = re.compile(r"[0-9a-f]{32}")
# A gateway log line's leading timestamp: ISO 8601 date, time, optional fraction and zone.
_STAMP: Final = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:[.,](\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?"
)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

type Json = Mapping[str, Any]
type HopName = Literal["notebook", "engine", "aigateway", "provider", "scoreboard"]
type HopState = Literal["ok", "fail", "grey"]
type Match = Literal["call_id", "time", "time-ambiguous", "none"]


@dataclass(frozen=True)
class Node:
    """One span in the tree; ``collapsed`` > 1 stands for that many same-named sibling leaves."""

    span: Mapping[str, Any]
    children: tuple[Node, ...]
    synthetic: bool
    collapsed: int


@dataclass(frozen=True)
class Hop:
    name: HopName
    state: HopState
    reason: str | None
    spans: int
    log_lines: int | None
    latency_ns: int | None


@dataclass(frozen=True)
class Call:
    span_id: str
    model: str | None
    provider: str | None
    cache: str | None
    tokens_in: int | None
    tokens_out: int | None
    spend: Decimal | None
    latency_ns: int | None
    status: str  # "error", "ok", or "unset" when neither the call nor its engine span says
    failure_code: str | None
    log_lines: tuple[str, ...]
    match: Match


@dataclass(frozen=True)
class Check:
    rule: str
    held: bool
    evidence: str


@dataclass(frozen=True)
class TraceStory:
    trace_ids: tuple[str, ...]
    verdict: str  # trace.json's: "pass", "fail", or "unknown"; never re-judged here
    wall_ns: int | None
    hops: tuple[Hop, ...]
    roots: tuple[Node, ...]
    calls: tuple[Call, ...]
    checks: tuple[Check, ...]
    notes: tuple[str, ...]
    cut: Mapping[str, int]
    events: int | None = None  # SDK events read (the header's count); None: not counted


# --- reading ----------------------------------------------------------------------------------


def _bytes(path: Path, cap: int) -> bytes | None:
    if not regular_file(path):
        return None
    try:
        with path.open("rb") as handle:
            return handle.read(cap)
    except OSError:
        return None


def _json(path: Path) -> Json:
    """The file's redacted JSON object; ``{}`` when absent, unreadable or not an object."""
    data = _bytes(path, tm.JSON_BYTES_CAP)
    try:
        value: object = None if data is None else json.loads(data)
        return redact_named_tree(value) if isinstance(value, dict) else {}
    except (ValueError, RecursionError):
        return {}


def _dict(value: object) -> Json:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _strs(value: object) -> list[str]:
    """The string items of ``value`` when it is a list; anything else is no items."""
    items: list[object] = list(value) if isinstance(value, list) else []  # pyright: ignore[reportUnknownArgumentType]
    return [item for item in items if isinstance(item, str)]


def _attrs(span: Json) -> Json:
    return _dict(span.get("attributes"))


def _sid(span: Json) -> str | None:
    return _str(span.get("span_id"))


def _parent(span: Json) -> str | None:
    parent = _str(span.get("parent_span_id"))
    return None if parent in _NO_PARENT else parent


def _start(span: Json) -> tuple[int, str]:
    return (tm.int_or_none(span.get("start_ns")) or 0, str(span.get("span_id")))


def is_error(span: Json) -> bool:
    """A failed span: an ``error`` status or an ``error.type`` attribute (the waterfall's rule)."""
    code = _dict(span.get("status")).get("code")
    return code == "error" or _str(_attrs(span).get("error.type")) is not None


def _extent(spans: Iterable[Json]) -> int | None:
    rows = list(spans)
    starts = [s for s in (tm.int_or_none(r.get("start_ns")) for r in rows) if s is not None]
    ends = [e for e in (tm.int_or_none(r.get("end_ns")) for r in rows) if e is not None]
    if not starts or not ends:
        return None
    return max(0, max(ends) - min(starts))


# --- client span (Review Focus 2) -------------------------------------------------------------


def _no_client_reason(orphans: Sequence[Json]) -> str | None:
    if len(orphans) != 1:
        if not orphans:
            return "no span has a parent outside the bundle"
        names = ", ".join(repr(str(o.get("name"))) for o in orphans[:3])
        return f"{len(orphans)} spans have a parent outside the bundle ({names})"
    name = orphans[0].get("name")
    return None if name == RUN_SPAN else f"the one orphan span is {name!r}, not {RUN_SPAN}"


def _client_span(spans: Sequence[Json], recorder: Json, notes: list[str]) -> Json | None:
    """The synthetic ``sdk.evaluate`` root, or None (and a note) when the shape is not one run."""
    ids = {sid for s in spans if (sid := _sid(s)) is not None}
    orphans = [s for s in spans if (p := _parent(s)) is not None and p not in ids]
    reason = _no_client_reason(orphans)
    if reason is not None:
        notes.append(f"no client span derived: {reason}")
        return None
    first = tm.int_or_none(recorder.get("first_event_ns"))
    last = tm.int_or_none(recorder.get("last_event_ns"))
    if first is None or last is None:
        notes.append("client span bounds unknown: recorder.json holds no event times")
    return {
        "trace_id": orphans[0].get("trace_id"),
        "span_id": _parent(orphans[0]),
        "parent_span_id": None,
        "name": CLIENT_SPAN,
        "kind": "client",
        "service": "notebook",
        "start_ns": first,
        "end_ns": last,
        "status": {"code": "unset", "message": ""},
        "attributes": {"workbench.derived_from": "SDK events (recorder.json)"},
    }


# --- tree (Review Focus 3) --------------------------------------------------------------------


def _name(span: Json) -> str:
    return str(span.get("name"))


def _links(ordered: Sequence[Json], notes: list[str]) -> tuple[list[int], dict[str, list[int]]]:
    """Root indices and children by parent id; a self-parent is a root, with a note."""
    ids = {sid for s in ordered if (sid := _sid(s)) is not None}
    roots: list[int] = []
    children: dict[str, list[int]] = {}
    for i, span in enumerate(ordered):
        parent, own = _parent(span), _sid(span)
        if parent is not None and parent == own:
            notes.append(f"span {_name(span)!r} ({own}) names itself as its own parent: a root")
        if parent is None or parent == own or parent not in ids:
            roots.append(i)
        else:
            children.setdefault(parent, []).append(i)
    return roots, children


@dataclass
class _Walk:
    """An iterative depth-first walk: each span is visited once, whatever the parent links say."""

    ordered: Sequence[Json]
    children: Mapping[str, list[int]]
    seen: set[int]
    order: list[int]  # pre-order: a parent always before its children
    kids: dict[int, list[int]]
    tops: list[int]

    def visit(self, start: int) -> None:
        self.seen.add(start)
        self.tops.append(start)
        stack = [start]
        while stack:
            i = stack.pop()
            self.order.append(i)
            sid = _sid(self.ordered[i])
            mine = [c for c in self.children.get(sid or "", []) if c not in self.seen]
            self.seen.update(mine)
            self.kids[i] = mine
            stack.extend(reversed(mine))


def _collapse(nodes: Sequence[Node]) -> tuple[Node, ...]:
    """Same-named sibling leaves, ``COLLAPSE_AT`` or more, fold into their first one. A failed
    span is never folded, so the path to an error always shows."""
    groups: dict[str, list[int]] = {}
    for k, node in enumerate(nodes):
        if not node.children and not node.synthetic and not is_error(node.span):
            groups.setdefault(_name(node.span), []).append(k)
    folds = [g for g in groups.values() if len(g) >= COLLAPSE_AT]
    heads = {g[0]: len(g) for g in folds}
    hidden = {k for g in folds for k in g[1:]}
    return tuple(
        replace(node, collapsed=heads[k]) if k in heads else node
        for k, node in enumerate(nodes)
        if k not in hidden
    )


def _tree(spans: Sequence[Json], synthetic: Json | None, notes: list[str]) -> tuple[Node, ...]:
    ordered: list[Json] = [*spans] if synthetic is None else [*spans, synthetic]
    ordered.sort(key=_start)
    roots, children = _links(ordered, notes)
    walk = _Walk(ordered, children, set(), [], {}, [])
    for root in roots:
        walk.visit(root)
    for i, span in enumerate(ordered):  # in start order; only a parent cycle is unseen here
        if i not in walk.seen:
            notes.append(f"span {_name(span)!r} ({_sid(span)}) is in a parent cycle: a root")
            walk.visit(i)
    built: dict[int, Node] = {}
    for i in reversed(walk.order):  # children before their parent: no recursion
        kids = _collapse([built[c] for c in walk.kids[i]])
        built[i] = Node(ordered[i], kids, ordered[i] is synthetic, 1)
    return tuple(built[i] for i in walk.tops)


# --- calls and their log lines (Review Focus 4) -----------------------------------------------


def _first(*values: object) -> object:
    return next((v for v in values if v is not None), None)


def _spend_by_model(accounting: Json | None) -> dict[str, tuple[int | None, Decimal | None]]:
    """Per model, summed over candidates: the accounted calls and their cost (None: unknown)."""
    totals: dict[str, tuple[int | None, Decimal | None]] = {}
    for candidate in tm.dicts(_dict(accounting).get("candidates")):
        for row in tm.dicts(candidate.get("by_model")):
            model = _str(row.get("model"))
            if model is None:
                continue
            calls, cost = totals.get(model, (0, Decimal(0)))
            more = tm.int_or_none(row.get("calls"))
            calls = None if calls is None or more is None else calls + more
            cost = tm.money_sum((cost, tm.money(_dict(row.get("usage")).get("cost_usd"))))
            totals[model] = (calls, cost)
    return totals


def _status(span: Json, parent: Json) -> str:
    if is_error(span) or is_error(parent):
        return "error"
    codes = {_dict(s.get("status")).get("code") for s in (span, parent)}
    return "ok" if "ok" in codes else "unset"


def _latency(span: Json) -> int | None:
    start, end = tm.int_or_none(span.get("start_ns")), tm.int_or_none(span.get("end_ns"))
    return None if start is None or end is None or end < start else end - start


def _call(span: Json, parent: Json, observed_codes: Sequence[str]) -> Call:
    """The call as its own attributes say, else as its engine parent span says."""
    own, up = _attrs(span), _attrs(parent)

    def fact(*keys: str) -> object:
        return _first(*(own.get(k) for k in keys), *(up.get(k) for k in keys))

    status = _status(span, parent)
    observed = ", ".join(observed_codes) or None
    return Call(
        span_id=str(span.get("span_id")),
        model=_str(fact("gen_ai.response.model", "gen_ai.request.model")),
        provider=_str(fact("gen_ai.provider.name")),
        cache=_str(fact("url4.cache_status")),
        tokens_in=tm.int_or_none(fact("gen_ai.usage.input_tokens")),
        tokens_out=tm.int_or_none(fact("gen_ai.usage.output_tokens")),
        spend=None,
        latency_ns=_latency(span),
        status=status,
        failure_code=_str(fact("error.type")) or (observed if status == "error" else None),
        log_lines=(),
        match="none",
    )


def _with_spend(calls: Sequence[Call], accounting: Json | None) -> list[Call]:
    totals = _spend_by_model(accounting)
    per_model: dict[str | None, int] = {}
    for call in calls:
        per_model[call.model] = per_model.get(call.model, 0) + 1

    def spend(call: Call) -> Decimal | None:
        accounted, cost = totals.get(call.model or "", (None, None))
        return cost if accounted == 1 and per_model[call.model] == 1 else None

    return [replace(c, spend=spend(c)) for c in calls]


def line_ns(line: str) -> int | None:
    """The line's leading ISO-8601 timestamp in Unix nanoseconds (no zone: UTC); else None."""
    stamp = _STAMP.match(line)
    if stamp is None:
        return None
    day, clock, fraction, zone = stamp.groups()
    zone = "+00:00" if zone in (None, "Z") else zone
    try:
        moment = datetime.fromisoformat(f"{day}T{clock}{zone}")
    except ValueError:
        return None
    delta = moment - _EPOCH
    seconds = delta.days * 86_400 + delta.seconds
    return seconds * 1_000_000_000 + int((fraction or "0").ljust(9, "0"))


@dataclass
class _Joined:
    lines: list[list[str]]
    windows: list[tuple[int, int, int]]  # (call index, start, end), sorted by start
    starts: list[int]  # the windows' starts, for bisection
    ambiguous: set[int]
    unmatched: int = 0
    placed: int = 0
    cut: int = 0  # lines a window held but ``TIME_MATCH_CAP`` left unplaced

    def place(self, line: str) -> None:
        at = line_ns(line)
        upto = 0 if at is None else bisect_right(self.starts, at)
        hits = [k for k, _, end in self.windows[:upto] if at is not None and at <= end]
        if not hits:
            self.unmatched += 1
        elif self.placed + len(hits) > TIME_MATCH_CAP:
            self.cut += 1
        else:
            self.placed += len(hits)
            for k in hits:
                self.lines[k].append(line)
            if len(hits) > 1:
                self.ambiguous.update(hits)


def _window(k: int, span: Json) -> tuple[int, int, int] | None:
    start, end = tm.int_or_none(span.get("start_ns")), tm.int_or_none(span.get("end_ns"))
    return None if start is None or end is None else (k, start, end)


def _match_logs(
    chats: Sequence[Json], calls: Sequence[Call], text: str, trace_ids: Iterable[str]
) -> tuple[list[Call], _Joined]:
    """Each call with its gateway log lines and how they matched; and the join's counts."""
    groups = tm.gateway_calls(text, trace_ids)
    claimed: dict[int, str] = {}
    for k, chat in enumerate(chats):
        call_id = _str(_attrs(chat).get("gateway_call_id"))
        if call_id is not None and call_id in groups:
            claimed[k] = call_id
    lines = [list(groups[claimed[k]].lines) if k in claimed else [] for k in range(len(chats))]
    windows = [w for k, c in enumerate(chats) if k not in claimed and (w := _window(k, c))]
    windows.sort(key=lambda w: w[1])
    joined = _Joined(lines, windows, [start for _, start, _ in windows], set())
    taken = set(claimed.values())
    for call_id, group in groups.items():
        for line in group.lines if call_id not in taken else ():
            joined.place(line)

    def match(k: int) -> Match:
        if k in claimed:
            return "call_id"
        return "time-ambiguous" if k in joined.ambiguous else "time" if joined.lines[k] else "none"

    out = [
        replace(c, log_lines=tuple(joined.lines[k]), match=match(k)) for k, c in enumerate(calls)
    ]
    return out, joined


def _observed_codes(trace: Json) -> list[str]:
    failures = tm.dicts(_dict(trace.get("observed")).get("failures"))
    return sorted({code for f in failures if (code := _str(f.get("code"))) is not None})


@dataclass(frozen=True)
class _Calls:
    calls: tuple[Call, ...]
    cut: int
    unmatched: int
    lines_cut: int


def _calls(spans: Sequence[Json], tele: tm.Telemetry, trace: Json, log: str) -> _Calls:
    by_id = {sid: s for s in spans if (sid := _sid(s)) is not None}
    chats: list[Json] = [s for s in spans if s.get("name") == CHAT_SPAN]
    chats.sort(key=_start)
    cut = max(0, len(chats) - CALLS_CAP)
    chats = chats[:CALLS_CAP]
    codes = _observed_codes(trace)
    calls = [_call(c, by_id.get(_parent(c) or "", {}), codes) for c in chats]
    calls = _with_spend(calls, tele.accounting)
    matched, joined = _match_logs(chats, calls, log, _trace_ids(trace, spans))
    return _Calls(tuple(matched), cut, joined.unmatched, joined.cut)


# --- hops (Review Focus 1, 5) -----------------------------------------------------------------


def _trace_hops(trace: Json) -> dict[str, Json]:
    return {name: h for h in tm.dicts(trace.get("hops")) if (name := _str(h.get("name")))}


def _hop_state(
    name: str, found: object, spans: int, failure: str | None
) -> tuple[HopState, str | None]:
    rules: tuple[tuple[bool, tuple[HopState, str | None]], ...] = (
        (found is False, ("fail", f"trace id missing from the {name} log")),
        (failure is not None, ("fail", failure)),
        (found is True, ("ok", None if spans else "no spans received")),
        (spans > 0, ("ok", f"log hop unknown: trace.json has no {name} hop")),
    )
    grey: tuple[HopState, str | None] = ("grey", f"no {name} evidence: no spans, no log hop")
    return next((outcome for holds, outcome in rules if holds), grey)


def _service_hop(name: HopName, spans: Sequence[Json], trace: Json, failure: str | None) -> Hop:
    hop = _trace_hops(trace).get(name, {})
    state, reason = _hop_state(name, hop.get("found"), len(spans), failure)
    return Hop(name, state, reason, len(spans), tm.int_or_none(hop.get("lines")), _extent(spans))


def _evaluate_error(trace: Json) -> str | None:
    """The SDK error the notebook caught, as its result records it: ``{"type", "code"}``. A
    notebook may catch it and finish cleanly (debug_failing_run), so ``error`` stays null."""
    caught = _dict(_dict(trace.get("result")).get("evaluate_error"))
    kind, code = _str(caught.get("type")), _str(caught.get("code"))
    if kind is None and code is None:
        return None
    return _short(f"{kind or 'error'}: {code or 'unknown code'}")


def _short(value: object) -> str | None:
    """A cell failure's last non-blank line (the root cause), capped: never a whole traceback."""
    lines = [line.strip() for line in (_str(value) or "").splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    return last if len(last) <= _REASON_CAP else last[: _REASON_CAP - 1] + "…"


def _notebook_hop(tele: tm.Telemetry, trace: Json, recorder: Json, synthetic: bool) -> Hop:
    first = tm.int_or_none(recorder.get("first_event_ns"))
    last = tm.int_or_none(recorder.get("last_event_ns"))
    latency = None if first is None or last is None else max(0, last - first)
    failure = _evaluate_error(trace) or _short(trace.get("error"))
    state: HopState = "grey" if not tele.events else "fail" if failure else "ok"
    reason = "no SDK events recorded" if not tele.events else failure
    return Hop("notebook", state, reason, int(synthetic), None, latency)


def _provider_hop(calls: Sequence[Call]) -> Hop:
    upstream = [c for c in calls if c.cache != "hit"]
    state: HopState = "ok" if upstream else "grey"
    reason = (
        "no model calls"
        if not calls
        else "none on replay: served from cache"
        if not upstream
        else f"{len(upstream)} of {len(calls)} calls went to the provider (no provider spans)"
    )
    return Hop("provider", state, reason, 0, None, None)


def _gateway_failure(calls: Sequence[Call]) -> str | None:
    failed = [c for c in calls if c.status == "error"]
    codes = sorted({c.failure_code or "unknown code" for c in failed})
    return f"{len(failed)} of {len(calls)} calls failed: {', '.join(codes)}" if failed else None


def _hops(
    spans: Sequence[Json],
    calls: Sequence[Call],
    tele: tm.Telemetry,
    trace: Json,
    recorder: Json,
    synthetic: bool,
) -> tuple[Hop, ...]:
    engine = [s for s in spans if s.get("service") == _ENGINE_SERVICE]
    gateway = [s for s in spans if s.get("service") == _GATEWAY_SERVICE]
    gateway_failure = _gateway_failure(calls)
    engine_errors = sum(is_error(s) for s in engine)
    engine_failure = (
        f"{engine_errors} engine spans failed" if engine_errors and not gateway_failure else None
    )
    return (
        _notebook_hop(tele, trace, recorder, synthetic),
        _service_hop("engine", engine, trace, engine_failure),
        _service_hop("aigateway", gateway, trace, gateway_failure),
        _provider_hop(calls),
        Hop("scoreboard", "grey", "not instrumented", 0, None, None),
    )


# --- checks -----------------------------------------------------------------------------------


def _yes(value: object) -> str:
    return "yes" if value is True else "no"


def _hop_check(hop: Json) -> Check:
    name = _str(hop.get("name")) or "unknown hop"
    lines = tm.int_or_none(hop.get("lines"))
    missing = _strs(hop.get("missing_ids"))
    evidence = f"{'unknown' if lines is None else lines} matching lines"
    evidence += f"; missing: {', '.join(missing)}" if missing else ""
    return Check(f"the {name} log carries the run's trace id", hop.get("found") is True, evidence)


def _expect_check(expect: Json, observed: Json) -> Check:
    codes = _strs(expect.get("failure_codes"))
    stage = _str(expect.get("stage")) or "unknown"
    pairs = {
        (_str(f.get("code")) or "unknown", _str(f.get("stage")) or "unknown")
        for f in tm.dicts(observed.get("failures"))
    }
    held = bool(pairs) and {c for c, _ in pairs} == set(codes)
    held = held and all((c, stage) in pairs for c in codes)
    seen = ", ".join(f"{c} at {s}" for c, s in sorted(pairs)) or "no failures"
    wanted = ", ".join(codes) or "no code"
    return Check(
        f"the run fails as declared: {wanted} at stage {stage}",
        held,
        f"expected {wanted} at {stage}; observed {seen}",
    )


def _checks(trace: Json) -> tuple[Check, ...]:
    checks = [_hop_check(h) for h in tm.dicts(trace.get("hops"))]
    lifecycle = _dict(trace.get("lifecycle"))
    if lifecycle:
        checks.append(
            Check(
                "the engine log shows the run scheduled and terminated",
                all(v is True for v in lifecycle.values()),
                " · ".join(f"{k}: {_yes(v)}" for k, v in lifecycle.items()),
            )
        )
    unattributed = tm.int_or_none(trace.get("unattributed_gateway_lines"))
    if unattributed is not None:
        checks.append(
            Check(
                "every aigateway line of this trace names its gateway_call_id",
                unattributed == 0,
                f"{unattributed} lines without a gateway_call_id",
            )
        )
    expect = _dict(trace.get("expect"))
    if expect:
        checks.append(_expect_check(expect, _dict(trace.get("observed"))))
    return tuple(checks)


# --- the story --------------------------------------------------------------------------------


def _trace_ids(trace: Json, spans: Sequence[Json]) -> tuple[str, ...]:
    ids = _strs(trace.get("trace_ids")) or [_str(s.get("trace_id")) or "" for s in spans]
    return tuple(dict.fromkeys(t for t in ids if _TRACE_ID.fullmatch(t)))


def _verdict(trace: Json) -> str:
    passed = trace.get("passed")
    return "unknown" if not isinstance(passed, bool) else "pass" if passed else "fail"


def _gateway_log(bundle_dir: Path) -> str:
    data = _bytes(bundle_dir / GATEWAY_LOG, LOG_CAP_BYTES)
    return "" if data is None else data.decode(errors="replace")


def _span_cut(tele: tm.Telemetry, notes: list[str]) -> int:
    """Spans cut by the writer and by this reader; a note when that count is not exact."""
    dropped = tele.dropped
    cut = dropped.spans_over_cap + (dropped.spans or 0)
    if dropped.spans is None:
        notes.append(
            "the bundle writer's dropped-span count is unknown (telemetry.json does not say): "
            "the span cut counts only this reader's cap"
        )
    if SPANS_FILE in dropped.truncated:
        notes.append(f"{SPANS_FILE} was cut at its byte cap: at least {cut} spans not shown")
    return cut


def build(bundle_dir: Path) -> TraceStory:
    """The run in ``bundle_dir`` as one story across every hop (see the module docstring)."""
    tele = tm.load(bundle_dir)
    trace, recorder = _json(bundle_dir / TRACE_FILE), _json(bundle_dir / RECORDER_FILE)
    spans: list[Json] = list(tele.spans)
    notes: list[str] = [] if spans else ["no spans received"]
    synthetic = _client_span(spans, recorder, notes) if spans else None
    roots = _tree(spans, synthetic, notes)
    found = _calls(spans, tele, trace, _gateway_log(bundle_dir))
    if found.unmatched:
        plural = "s" if found.unmatched != 1 else ""
        notes.append(
            f"{found.unmatched} gateway log line{plural} of this trace with a gateway_call_id "
            "matched no model call (no gateway_call_id on the gateway span, and no timestamp "
            "inside a call's window)"
        )
    if found.lines_cut:
        notes.append(
            f"{found.lines_cut} time-matched gateway log lines not shown: over the "
            f"{TIME_MATCH_CAP} placement cap"
        )
    span_cut = _span_cut(tele, notes) if spans else tele.dropped.spans_over_cap
    return TraceStory(
        trace_ids=_trace_ids(trace, spans),
        verdict=_verdict(trace),
        wall_ns=_extent([*spans, *([synthetic] if synthetic is not None else [])]),
        hops=_hops(spans, found.calls, tele, trace, recorder, synthetic is not None),
        roots=roots,
        calls=found.calls,
        checks=_checks(trace),
        notes=tuple(notes),
        cut={"spans": span_cut, "calls": found.cut, "log_lines": found.lines_cut},
        events=len(tele.events) if EVENTS_FILE in tele.found else None,
    )
