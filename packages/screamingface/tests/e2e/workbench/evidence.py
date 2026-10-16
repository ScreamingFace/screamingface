"""Collect a run's trace chain from a target's log sources (e2e workbench spec §3.3)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from harness.trace_evidence import unattributed_gateway_lines

_MAX_LINES = 500
# The stable prefixes of `screamingface_engine.run_evidence` (SCHEDULED, TERMINATED).
_SCHEDULED = "run scheduled"
_TERMINATED = "run terminated"


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
    name: str
    found: bool
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TraceChain:
    trace_ids: tuple[str, ...]
    hops: tuple[Hop, ...]
    lifecycle: dict[str, bool] = field(default_factory=dict)
    unattributed: list[str] = field(default_factory=list)

    def missing(self, required: Sequence[str]) -> list[str]:
        found = {h.name for h in self.hops if h.found}
        return [name for name in required if name not in found]

    def to_json(self) -> dict[str, Any]:
        return {
            "trace_ids": list(self.trace_ids),
            "hops": [{"name": h.name, "found": h.found, "lines": len(h.lines)} for h in self.hops],
            "lifecycle": dict(self.lifecycle),
            "unattributed_gateway_lines": len(self.unattributed),
        }


def _matching(text: str, trace_ids: Sequence[str]) -> tuple[str, ...]:
    if not trace_ids:
        return ()
    hits = [ln for ln in text.splitlines() if any(t in ln for t in trace_ids)]
    return tuple(hits[:_MAX_LINES])


def _has_event(lines: Sequence[str], event: str) -> bool:
    """WHY the substring check: log formatters may prepend a timestamp and level."""
    return any(ln.startswith(event) or f" {event} " in ln for ln in lines)


def collect(trace_ids: Sequence[str], sources: Sequence[LogSource]) -> TraceChain:
    hops: list[Hop] = []
    lifecycle = {"scheduled": False, "terminated": False}
    unattributed: list[str] = []
    for source in sources:
        text = source.read()
        lines = _matching(text, trace_ids)
        hops.append(Hop(source.name, bool(lines), lines))
        lifecycle["scheduled"] |= _has_event(lines, _SCHEDULED)
        lifecycle["terminated"] |= _has_event(lines, _TERMINATED)
        if source.name == "aigateway":
            unattributed += unattributed_gateway_lines(text)[1]
    return TraceChain(tuple(trace_ids), tuple(hops), lifecycle, unattributed)
