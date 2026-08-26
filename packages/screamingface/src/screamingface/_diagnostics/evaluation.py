"""In-flight, privacy-safe context for one Client Evaluation."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from screamingface._diagnostics.capture import (
    _client_document,
    _engine_document,
    _error_document,
)
from screamingface._diagnostics.model import _new_receipt
from screamingface._diagnostics.store import _STORE
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface.diagnostic import DiagnosticReceipt
from screamingface.events import Event, Terminated

_SESSION_ID = f"session_{uuid4().hex}"
_MAX_BREADCRUMBS = 20


class _EvaluationDiagnostic:
    """Accumulate only allow-listed evidence while one Evaluation advances."""

    def __init__(
        self,
        *,
        engine_url: str,
        benchmark: object,
        mode: str | None = None,
    ) -> None:
        self._context: dict[str, object] = {"engine": _engine_document(engine_url)}
        if isinstance(benchmark, str):
            self._context["benchmark"] = {"id": benchmark}
        if mode is not None:
            self._context["mode"] = mode
        self._executions: dict[str, dict[str, object]] = {}
        self._breadcrumbs: list[dict[str, object]] = []
        self._lock = Lock()
        self._started_at = time.monotonic()

    def compiled(self, evaluation: _Evaluation) -> None:
        candidates = [_candidate_document(candidate) for candidate in evaluation.candidates]
        with self._lock:
            self._context["benchmark"] = {
                "id": evaluation.benchmark.id,
                "revision": evaluation.benchmark.revision,
                "case_count": evaluation.case_count,
            }
            self._context["candidates"] = candidates

    def validated(self, evaluation: _Evaluation) -> None:
        parameters = {
            candidate.name: [
                {
                    "operation_id": assignment.operation_id,
                    "model": assignment.model,
                    "values": dict(assignment.params),
                }
                for assignment in candidate.parameter_assignments
            ]
            for candidate in evaluation.candidates
        }
        with self._lock:
            candidates = self._context.get("candidates")
            if not isinstance(candidates, list):
                raise AssertionError("compiled candidates must precede validation")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise AssertionError("diagnostic candidates must remain objects")
                name = candidate.get("name")
                if isinstance(name, str):
                    candidate["parameters"] = parameters[name]

    def compiled_candidate(self, candidate: Candidate) -> None:
        with self._lock:
            self._context["candidates"] = [_candidate_document(candidate)]

    def begin(self, candidate: Candidate) -> None:
        with self._lock:
            self._executions.setdefault(
                candidate.name,
                {"candidate": candidate.name, "status": "running"},
            )
            self._append_breadcrumb(candidate.name, "execution", "started")

    def observe(self, candidate: Candidate, event: Event) -> None:
        with self._lock:
            execution = self._executions.setdefault(
                candidate.name,
                {"candidate": candidate.name, "status": "running"},
            )
            execution["run_id"] = event.run_id
            if trace_id := _trace_id(event.traceparent):
                execution["trace_id"] = trace_id
            if isinstance(event, Terminated):
                execution["status"] = event.status
            self._append_breadcrumb(
                candidate.name,
                "execution",
                event.kind,
                sequence=event.sequence,
                outcome=event.status if isinstance(event, Terminated) else None,
            )

    def receipt(self, error: BaseException) -> DiagnosticReceipt:
        if isinstance(error, KeyboardInterrupt):
            outcome = "interrupted_by_user"
        elif isinstance(error, asyncio.CancelledError):
            outcome = "cancelled"
        else:
            outcome = "failed"
        with self._lock:
            context = dict(self._context)
            executions = tuple(dict(value) for value in self._executions.values())
            breadcrumbs = tuple(dict(value) for value in self._breadcrumbs)
        return _new_receipt(
            diagnostic_id=f"diag_{uuid4().hex}",
            session_id=_SESSION_ID,
            occurred_at=datetime.now(UTC),
            elapsed_seconds=max(0.0, time.monotonic() - self._started_at),
            operation="evaluate",
            outcome=outcome,
            client=_client_document(),
            error=_error_document(error),
            context=context,
            executions=executions,
            breadcrumbs=breadcrumbs,
        )

    def stage(self, error: BaseException) -> DiagnosticReceipt | None:
        receipt = self.receipt(error)
        return receipt if _STORE.add(receipt) else None

    def _append_breadcrumb(
        self,
        candidate: str,
        stage: str,
        event: str,
        *,
        sequence: int | None = None,
        outcome: str | None = None,
    ) -> None:
        breadcrumb: dict[str, object] = {
            "candidate": candidate,
            "stage": stage,
            "event": event,
        }
        if sequence is not None:
            breadcrumb["sequence"] = sequence
        if outcome is not None:
            breadcrumb["outcome"] = outcome
        self._breadcrumbs.append(breadcrumb)
        if len(self._breadcrumbs) > _MAX_BREADCRUMBS:
            del self._breadcrumbs[0]


def _candidate_document(candidate: Candidate) -> dict[str, object]:
    return {
        "name": candidate.name,
        "kind": candidate.kind,
        "models": list(candidate.models),
        "operations": [
            {
                "id": operation.id,
                "kind": operation.kind,
                "depends_on": list(operation.depends_on),
            }
            for operation in candidate.operations
        ],
        "parameters": [],
    }


def _trace_id(traceparent: str | None) -> str | None:
    if traceparent is None:
        return None
    parts = traceparent.split("-")
    if len(parts) == 4:
        version, trace_id, parent_id, flags = parts
        if (
            _hex(version, 2)
            and version != "ff"
            and _hex(trace_id, 32)
            and trace_id != "0" * 32
            and _hex(parent_id, 16)
            and parent_id != "0" * 16
            and _hex(flags, 2)
        ):
            return trace_id.lower()
    return None


def _hex(value: str, length: int) -> bool:
    return len(value) == length and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


__all__ = ["_EvaluationDiagnostic"]
