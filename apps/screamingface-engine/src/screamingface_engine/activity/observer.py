"""Activity adapter for execution-owned observation interfaces."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType

from screamingface_engine.activity.contract import MAX_INTEGER, ActivityKind
from screamingface_engine.activity.scope import Operation, operation
from screamingface_engine.activity.session import ActivitySession, activate
from screamingface_engine.observations import LogEmitter, Scalar


class ActivityObserver:
    def __init__(self, *, enabled: bool = True) -> None:
        self.session = ActivitySession() if enabled else None
        self._calls: set[Operation] = set()

    def bind(self) -> AbstractContextManager[None]:
        return activate(self.session)

    async def aclose(self) -> None:
        if self.session is not None:
            self.session.revoke()
        # INVARIANT: abandoned call tasks cannot retain heartbeat resources after the run.
        for call in tuple(self._calls):
            await call.stop_heartbeat()
        self._calls.clear()

    def model_call(self, model_id: str, emit: LogEmitter | None) -> ActivityModelCall:
        return ActivityModelCall(
            self, operation(emit=emit, kind=ActivityKind.MODEL_CALL, model_id=model_id)
        )

    def bridge_loss(self, dropped: int) -> dict[str, Scalar]:
        if self.session is None or not self.session.active:
            return {}
        return {
            "sf.telemetry.schema": "screamingface.telemetry.v1",
            "sf.telemetry.loss.scope": "engine_bridge_logs",
            "sf.telemetry.loss.dropped_total": min(MAX_INTEGER, dropped),
        }


class ActivityModelCall:
    def __init__(self, owner: ActivityObserver, scope: Operation) -> None:
        self._owner, self._scope = owner, scope

    async def start(self) -> None:
        self._owner._calls.add(self._scope)
        await self._scope.__aenter__()

    async def close(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            await self._scope.__aexit__(exc_type, exc, tb)
        finally:
            self._owner._calls.discard(self._scope)

    def completed(self, finish_reason: str | None) -> None:
        self._scope.finish(finish_reason=finish_reason)

    def failed(self, code: str) -> None:
        self._scope.finish(
            outcome="refused" if code == "provider_refusal" else "failed", failure_code=code
        )

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        self._scope.retry(attempt=attempt, delay_seconds=delay_seconds)
