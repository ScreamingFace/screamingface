"""Activity adapter for execution-owned observation interfaces."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType

from screamingface_engine.activity.case_grading import emit_case_grading
from screamingface_engine.activity.contract import MAX_INTEGER, ActivityKind, safe_fact
from screamingface_engine.activity.scope import Operation, operation, stop_heartbeats
from screamingface_engine.activity.session import ActivitySession, activate
from screamingface_engine.benchmarks.case_context import current_case_id, current_case_position
from screamingface_engine.benchmarks.contract import CaseId
from screamingface_engine.benchmarks.grading_activity import GradingState
from screamingface_engine.benchmarks.stages import StageScope
from screamingface_engine.observations import LogEmitter, ModelObservation, Scalar


class ActivityObserver:
    def __init__(self, *, enabled: bool = True) -> None:
        self.session = ActivitySession() if enabled else None
        self._calls: set[Operation] = set()
        self._grading: set[str] = set()

    def bind(self) -> AbstractContextManager[None]:
        return activate(self.session)

    async def aclose(self) -> None:
        if self.session is not None:
            self.session.revoke()
        # INVARIANT: abandoned call tasks cannot retain heartbeat resources after the run.
        self._grading.clear()
        calls = tuple(self._calls)
        self._calls.clear()
        await stop_heartbeats(calls)

    def model_call(self, model_id: str, emit: LogEmitter | None) -> ModelObservation:
        if self.session is None or not self.session.active:
            return _INERT_MODEL_CALL
        return ActivityModelCall(
            self,
            operation(emit=emit, kind=ActivityKind.MODEL_CALL, model_id=model_id, **_case_facts()),
        )

    def stage(self, stage: ActivityKind, emit: LogEmitter | None) -> StageScope | None:
        if self.session is None or not self.session.active or emit is None:
            return None
        return ActivityStage(self, operation(emit=emit, kind=stage, **_case_facts()))

    def case_grading(self, case_id: CaseId, state: GradingState, emit: LogEmitter | None) -> None:
        emit_case_grading(self.session, emit, case_id, state, self._grading)

    def bridge_loss(self, dropped: int) -> dict[str, Scalar]:
        if self.session is None or not self.session.active:
            return {}
        return {
            "sf.telemetry.schema": "screamingface.telemetry.v1",
            "sf.telemetry.loss.scope": "engine_bridge_logs",
            "sf.telemetry.loss.dropped_total": max(0, min(MAX_INTEGER, dropped)),
        }


class ActivityStage:
    """Track stage resources alongside calls so run cleanup also joins abandoned stages."""

    def __init__(self, owner: ActivityObserver, scope: Operation) -> None:
        self._owner, self._scope = owner, scope

    def __enter__(self) -> None:
        self._owner._calls.add(self._scope)
        self._scope.__enter__()

    def __exit__(self, typ, exc, tb) -> None:
        try:
            self._scope.__exit__(typ, exc, tb)
        finally:
            self._owner._calls.discard(self._scope)

    async def __aenter__(self) -> None:
        self._owner._calls.add(self._scope)
        await self._scope.__aenter__()

    async def __aexit__(self, typ, exc, tb) -> None:
        try:
            await self._scope.__aexit__(typ, exc, tb)
        finally:
            self._owner._calls.discard(self._scope)


class ActivityModelCall(ActivityStage):
    async def start(self) -> None:
        await self.__aenter__()

    async def close(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.__aexit__(exc_type, exc, tb)

    def completed(self, finish_reason: str | None) -> None:
        self._scope.finish(finish_reason=finish_reason)

    def failed(self, code: str) -> None:
        self._scope.finish(
            outcome="refused" if code == "provider_refusal" else "failed", failure_code=code
        )

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        self._scope.retry(attempt=attempt, delay_seconds=delay_seconds)


class _InertModelCall:
    """Shared stateless callbacks: disabled runs need only their run-level context mask."""

    async def start(self) -> None:
        pass

    async def close(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def completed(self, finish_reason: str | None) -> None:
        pass

    def failed(self, code: str) -> None:
        pass

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        pass


_INERT_MODEL_CALL = _InertModelCall()


def _case_facts() -> dict[str, Scalar]:
    case_id = current_case_id()
    if case_id is None:
        return {}
    try:
        result = {"case_id": safe_fact("case_id", case_id)}
        if position := current_case_position():
            result.update(
                case_position=safe_fact("case_position", position[0]),
                case_count=safe_fact("case_count", position[1]),
            )
        return result
    except ValueError:
        # WHY: a legitimate benchmark ID outside the telemetry allowlist must not
        # suppress the whole model event or leak arbitrary/private identifier text.
        return {}
