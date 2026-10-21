"""Collect a run's trace chain from a target's log sources (e2e workbench spec §3.3)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from harness.trace_evidence import CALL_ID_MARK, unattributed_gateway_lines

_MAX_LINES = 500
# The stable prefixes of `screamingface_engine.run_evidence` (SCHEDULED, TERMINATED).
_SCHEDULED = "run scheduled"
_TERMINATED = "run terminated"
_GATEWAY = "aigateway"


class LogSource(Protocol):
    # Read-only so frozen dataclasses (FileLogSource) satisfy it.
    @property
    def name(self) -> str: ...

    def read(self) -> str: ...


@dataclass(frozen=True)
class FileLogSource:
    name: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(errors="replace") if self.path.is_file() else ""


# `screamingface._runtime.runtime_logging.RuntimeLog._write_line`: "<iso-ts> [<service>] <line>".
_RUNTIME_TAG = re.compile(r"^\S+ \[([^\]]+)\] ")


@dataclass(frozen=True)
class ServiceLogSource:
    """One service's lines of the local runtime's shared ``runtime.log``, as its own hop.

    WHY: ``screamingface up`` runs the engine and the gateway in one process writing one log;
    each line carries its service tag (``engine``, ``gateway``, ``scoreboard``, ``supervisor``),
    so filtering by tag gives the same per-hop view the replay stack's separate files give.
    """

    name: str
    path: Path
    service: str

    def read(self) -> str:
        if not self.path.is_file():
            return ""
        kept = [
            ln
            for ln in self.path.read_text(errors="replace").splitlines()
            if (tag := _RUNTIME_TAG.match(ln)) is not None and tag.group(1) == self.service
        ]
        return "".join(f"{ln}\n" for ln in kept)


@dataclass(frozen=True)
class Hop:
    """One log source's view of the run. ``found`` means EVERY trace id is in it."""

    name: str
    found: bool
    lines: tuple[str, ...]
    found_ids: tuple[str, ...] = ()
    # Ids that appear on at least one line also carrying a ``gateway_call_id``.
    identified_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraceChain:
    trace_ids: tuple[str, ...]
    hops: tuple[Hop, ...]
    lifecycle: dict[str, bool] = field(default_factory=dict)
    unattributed: list[str] = field(default_factory=list)

    def missing(self, required: Sequence[str]) -> list[str]:
        """Every (required hop, trace id) gap, each naming the hop and the absent id.

        WHY per id: a run reporting two ids whose second never reached the gateway is a broken
        chain, though a per-hop "any id matched" check would pass it.

        The ``aigateway`` hop also needs, per id, a line carrying BOTH that id and a
        ``gateway_call_id``: a gateway that logs the trace id but no call id has a hop that
        exists yet attributes no call. This is the workbench's form of the correlation
        ladder's rung 3 (which wants >=2 identified lines in its own window): >=1 identified
        line per id, bound to this run by the id rather than by a time window, so another
        run's identified lines in a shared log cannot satisfy it.
        """
        by_name = {h.name: h for h in self.hops}
        gaps: list[str] = []
        for name in required:
            hop = by_name.get(name)
            if hop is None:
                gaps.append(f"{name}: no log source")
                continue
            if not self.trace_ids:
                gaps.append(f"{name}: no trace id to match")
                continue
            for tid in self.trace_ids:
                if tid not in hop.found_ids:
                    gaps.append(f"{name}: trace {tid} absent")
                elif name == _GATEWAY and tid not in hop.identified_ids:
                    gaps.append(f"{name}: trace {tid} on no line carrying gateway_call_id")
        return gaps

    def reasons(self, required: Sequence[str]) -> list[str]:
        """The chain's failure reasons for the test verdict. No ids → no chain reason, since
        ``check_result`` already fails that run (it would only be reported twice)."""
        out: list[str] = []
        if self.trace_ids and (gaps := self.missing(required)):
            out.append(f"trace chain incomplete: {'; '.join(gaps)}")
        if self.unattributed:
            out.append(f"{len(self.unattributed)} aigateway lines lack gateway_call_id")
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "trace_ids": list(self.trace_ids),
            "hops": [
                {
                    "name": h.name,
                    "found": h.found,
                    "lines": len(h.lines),
                    "missing_ids": [t for t in self.trace_ids if t not in h.found_ids],
                }
                for h in self.hops
            ],
            "lifecycle": dict(self.lifecycle),
            "unattributed_gateway_lines": len(self.unattributed),
        }


# The `trace_id=<32 lowercase hex>` field both services render (engine `logs.RunContextFilter`,
# `run_evidence`; aigateway `logs.CallContextFilter`): space-joined `key=value` parts, so a
# token is bounded by whitespace or the line's ends.
_TRACE_ID_TOKEN = re.compile(r"(?<!\S)trace_id=([0-9a-f]{32})(?!\S)")


def trace_id_tokens(line: str) -> frozenset[str]:
    """Every exact ``trace_id=<32 lowercase hex>`` value on one log line.

    WHY a parser and not ``tid in line``: a substring check passes ``trace_id=aa<id>bb`` or a
    ``parent_trace_id=<id>`` — a line that is not this run's evidence. The verdict
    (``found_ids``/``identified_ids``) and the excerpt (``Hop.lines``) both go through this one
    function, so the evidence shown can never disagree with the verdict it supports.
    """
    return frozenset(_TRACE_ID_TOKEN.findall(line))


def _has_event(lines: Sequence[str], event: str) -> bool:
    """WHY the substring check: log formatters may prepend a timestamp and level."""
    return any(ln.startswith(event) or f" {event} " in ln for ln in lines)


# A gateway LOG RECORD carries a level (`INFO:`, `WARNING:` …). Anything else captured from the
# process — LiteLLM's stdout `print()` "Provider List" banner and its blank lines, a stderr
# warning — is not a record and cannot carry a call id; rung 3 scopes it out (OME-938). Seen
# inside the request window on the first paid local run (2026-10-21).
_LOG_RECORD: Final = re.compile(r"\b(?:DEBUG|INFO|WARNING|ERROR|CRITICAL):")


def _log_records(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if _LOG_RECORD.search(ln))


def collect(trace_ids: Sequence[str], sources: Sequence[LogSource]) -> TraceChain:
    hops: list[Hop] = []
    lifecycle = {"scheduled": False, "terminated": False}
    unattributed: list[str] = []
    for source in sources:
        text = source.read()
        wanted = frozenset(trace_ids)
        # (line, the run's ids on it): only lines carrying an exact token for one of our ids.
        hits = [(ln, ids) for ln in text.splitlines() if (ids := trace_id_tokens(ln) & wanted)]
        seen = frozenset().union(*(ids for _, ids in hits))
        called = frozenset().union(*(ids for ln, ids in hits if CALL_ID_MARK in ln))
        found = tuple(t for t in trace_ids if t in seen)
        identified = tuple(t for t in found if t in called)
        lines = tuple(ln for ln, _ in hits[:_MAX_LINES])
        every = bool(trace_ids) and len(found) == len(trace_ids)
        hops.append(Hop(source.name, every, lines, found, identified))
        lifecycle["scheduled"] |= _has_event(lines, _SCHEDULED)
        lifecycle["terminated"] |= _has_event(lines, _TERMINATED)
        if source.name == _GATEWAY:
            unattributed += unattributed_gateway_lines(_log_records(text))[1]
    return TraceChain(tuple(trace_ids), tuple(hops), lifecycle, unattributed)
