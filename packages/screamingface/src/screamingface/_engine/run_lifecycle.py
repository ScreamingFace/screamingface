"""Pure URL4 run-stream state and command framing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from screamingface._core.ports import _RunOutcome
from screamingface._engine.contract import _RunState
from screamingface._evaluation.model import Candidate
from screamingface.events import Event


@dataclass(frozen=True, slots=True)
class _LifecycleStep:
    command: str | None = None
    event: Event | None = None
    outcome: _RunOutcome | None = None


class _Lifecycle:
    """Shared protocol decisions; adapters provide only synchronous/asynchronous I/O."""

    def __init__(self, candidate: Candidate) -> None:
        self._state = _RunState(candidate.url4)

    @staticmethod
    def initial_attach() -> str:
        return _attach(None)

    def resume_attach(self) -> str:
        """The attach frame for a NEW socket resuming a started Run.

        Replays from the first frame this Run has not yet accepted (`last_sequence + 1`,
        the same inclusive-from convention the in-connection gap replay uses). A Run with
        no accepted frames resumes from the start.
        """
        last = self._state.last_sequence
        return _attach(None if last < 1 else last + 1)

    @staticmethod
    def stop() -> str:
        return _stop("client stopped consuming events")

    def accept(self, frame: str | bytes) -> _LifecycleStep:
        accepted = self._state.accept(frame)
        command = None if accepted.replay_from is None else _attach(accepted.replay_from)
        return _LifecycleStep(
            command=command,
            event=accepted.event,
            outcome=accepted.outcome,
        )


def _attach(from_sequence: int | None) -> str:
    return _command("ai.url4.attach", {"from_sequence": from_sequence})


def _stop(reason: str) -> str:
    return _command("ai.url4.stop", {"reason": reason})


def _command(kind: str, data: dict[str, object]) -> str:
    return json.dumps(
        {
            "specversion": "1.0",
            "id": uuid4().hex,
            "source": "/screamingface/client",
            "time": datetime.now(UTC).isoformat(),
            "type": kind,
            "datacontenttype": "application/json",
            "data": data,
        },
        separators=(",", ":"),
    )


__all__: list[str] = []
