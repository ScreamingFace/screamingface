"""Rolling optional telemetry; never a source of scores or execution decisions."""

from collections import OrderedDict
from dataclasses import dataclass

from screamingface._ui.activity_record import (
    MAX_INTEGER,
    PREFIX,
    TERMINAL,
    ActivityRecord,
    decode,
    number,
)
from screamingface.events import Log


@dataclass(frozen=True)
class ActivityRow:
    candidate: int
    run: str
    record: ActivityRecord
    ended: bool
    historical: bool = False


class ActivityLog:
    """One bounded history shared by compact and detailed notebook views."""

    def __init__(self, *, limit: int = 2000, byte_limit: int = 8 * 1024 * 1024) -> None:
        self._limit, self._byte_limit = limit, byte_limit
        self._history: OrderedDict[tuple[int, str, str, int], ActivityRecord] = OrderedDict()
        self._latest: dict[tuple[int, str, str], ActivityRecord] = {}
        self._bytes = 0
        self._ended: set[int] = set()
        self.invalid = self.unsupported = self.truncated = self.gaps = 0
        # WHY: indexes come from the finite Evaluation, never incoming event IDs.
        self.suppressed: dict[int, dict[str, int]] = {}
        self.bridge_loss: dict[int, int] = {}

    @property
    def retained(self) -> int:
        return len(self._history)

    def observe(self, candidate: int, event: Log) -> None:
        try:
            self._observe(candidate, event)
        except ValueError:
            self.invalid = min(MAX_INTEGER, self.invalid + 1)

    def _observe(self, candidate: int, event: Log) -> None:
        attrs = event.attributes
        if attrs.get("sf.telemetry.schema") == "screamingface.telemetry.v1":
            self._loss(candidate, event)
        elif attrs.get(PREFIX + "schema") == "screamingface.activity.v1":
            self._activity(candidate, event)
        elif PREFIX + "schema" in attrs:
            self.unsupported = min(MAX_INTEGER, self.unsupported + 1)

    def _loss(self, candidate: int, event: Log) -> None:
        attrs = event.attributes
        if attrs.get("sf.telemetry.loss.scope") == "engine_bridge_logs":
            count = int(number(attrs.get("sf.telemetry.loss.dropped_total")))
            self.bridge_loss[candidate] = max(self.bridge_loss.get(candidate, 0), count)

    def _activity(self, candidate: int, event: Log) -> None:
        if len(event.run_id.encode()) > 128:
            raise ValueError("oversize run identifier")
        record = decode(event)
        counts = {
            reason: int(number(event.attributes[PREFIX + "suppressed." + reason]))
            for reason in ("invalid", "oversize", "rate")
            if PREFIX + "suppressed." + reason in event.attributes
        }
        if counts and len(counts) != 3:
            raise ValueError("incomplete suppression snapshot")
        snapshot = self.suppressed.setdefault(candidate, {})
        for reason, count in counts.items():
            snapshot[reason] = max(snapshot.get(reason, 0), count)
        key = candidate, event.run_id, record.id
        previous = self._latest.get(key)
        if previous and (record.revision <= previous.revision or previous.state in TERMINAL):
            return
        if previous and (record.kind != previous.kind):
            self.invalid = min(MAX_INTEGER, self.invalid + 1)
            return
        if previous and record.revision > previous.revision + 1:
            self.gaps = min(MAX_INTEGER, self.gaps + 1)
        self._retain(key, record)

    def _retain(self, key: tuple[int, str, str], record: ActivityRecord) -> None:
        self._history[(*key, record.revision)] = record
        self._latest[key] = record
        self._bytes += record.size + len(key[1].encode())
        while len(self._history) > self._limit or self._bytes > self._byte_limit:
            old_key = next(
                (
                    k
                    for k, r in self._history.items()
                    if r is not self._latest.get(k[:3]) or r.state == "completed"
                ),
                next(iter(self._history)),
            )
            old = self._history.pop(old_key)
            self._bytes -= old.size + len(old_key[1].encode())
            if self._latest.get(old_key[:3]) is old:
                del self._latest[old_key[:3]]
            self.truncated = min(MAX_INTEGER, self.truncated + 1)

    def end(self, candidate: int) -> None:
        self._ended.add(candidate)

    def history(self) -> list[ActivityRow]:
        """Accepted transitions in receive order, within the existing rolling bounds."""
        return [
            ActivityRow(
                candidate,
                run,
                record,
                candidate in self._ended,
                self._latest.get((candidate, run, operation)) is not record,
            )
            for (candidate, run, operation, _), record in self._history.items()
        ]

    def rows(self, *, detailed: bool = False) -> list[ActivityRow]:
        return [
            ActivityRow(candidate, run, record, candidate in self._ended)
            for (candidate, run, _), record in self._latest.items()
            if detailed
            or record.kind != "model_call"
            or record.state in {"failed", "cancelled", "refused", "retrying"}
            or (record.state not in TERMINAL and record.elapsed_ms >= 60000)
        ]
