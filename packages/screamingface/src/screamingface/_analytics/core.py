"""Consent-gated operation records, with no knowledge of HTTP, files or product data."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from screamingface._analytics.ports import AnalyticsSink, Consent, ConsentStore, Event

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Operation:
    name: str
    fields: Event
    consent: Consent
    started: float
    generation: int


def duration_bucket(seconds: float) -> str:
    for ceiling, label in (
        (1, "under_1s"),
        (10, "1_10s"),
        (60, "10_60s"),
        (600, "1_10m"),
        (3600, "10_60m"),
    ):
        if seconds < ceiling:
            return label
    return "over_60m"


class Coordinator:
    def __init__(self, store: ConsentStore, sink: AnalyticsSink, *, version: str) -> None:
        self.store, self.sink, self.version = store, sink, version
        self._session: str | None = None
        self._continuity: Consent | None = None
        self._lock = threading.RLock()
        self._generation = 0

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._session = None
            self.sink.clear()

    def accepts(self, event: Event) -> bool:
        with self._lock:
            consent = self.store.read()
            return (
                consent.choice == "accepted"
                and event.get("session_id") == self._session
                and event.get("persistent_id") == consent.installation_id
            )

    def begin(
        self, name: str, workflow: str, interface: str, origin: str, mode: str
    ) -> Operation | None:
        if origin not in {"python", "local_jupyter", "cli"} or mode not in {"byok", "hosted"}:
            _LOG.debug("Analytics skipped: unavailable operation metadata")
            return None
        with self._lock:
            consent = self.store.read()
            if consent.choice != "accepted":
                return None
            self._ensure_session(consent)
            fields = self._fields(workflow, interface, origin, mode, consent)
            operation = Operation(name, fields, consent, time.monotonic(), self._generation)
            self._emit(operation, "started", {})
            return operation

    def _ensure_session(self, consent: Consent) -> None:
        if self._session is None or self._continuity != consent:
            # INVARIANT: a reset in another process must not join old/new IDs through
            # this process's session. Ordinary Client replacement never resets it.
            self.clear()
            self._session = str(uuid4())
            self._continuity = consent

    def _fields(
        self, workflow: str, interface: str, origin: str, mode: str, consent: Consent
    ) -> Event:
        fields = {
            "operation_id": str(uuid4()),
            "session_id": str(self._session),
            "sdk_version": self.version,
            "surface": "python_sdk",
            "interface": interface,
            "origin": origin,
            "usage_mode": mode,
            "workflow": workflow,
            "id_scope": "session",
        }
        if consent.installation_id:
            fields.update(persistent_id=consent.installation_id, id_scope="installation")
        return fields

    def finish(self, operation: Operation, outcome: str) -> None:
        with self._lock:
            if operation.generation != self._generation or self.store.read() != operation.consent:
                return
            self._emit(
                operation,
                "finished",
                {
                    "outcome": outcome,
                    "duration_bucket": duration_bucket(time.monotonic() - operation.started),
                },
            )

    def _emit(self, operation: Operation, suffix: str, extra: Event) -> None:
        # INVARIANT: product objects, exceptions and execution IDs never enter this map.
        self.sink.emit(
            {
                **operation.fields,
                **extra,
                "event": f"{operation.name}_{suffix}",
                "event_id": str(uuid4()),
                "timestamp": datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
        )
