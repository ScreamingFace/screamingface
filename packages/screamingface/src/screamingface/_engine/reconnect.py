"""Per-outage recovery accounting shared by both WebSocket transports."""

from dataclasses import dataclass


@dataclass
class _RecoveryWindow:
    budget_s: float
    attempts: int = 0
    _deadline: float | None = None
    _connected_at: float | None = None

    def connected(self, now: float) -> None:
        self._connected_at = now

    def failed(self, now: float) -> float:
        """Return the current outage deadline, refreshing only after stable recovery."""
        stable = self._connected_at is not None and now - self._connected_at >= self.budget_s
        # FEATURE: OME-1141 — healthy Evaluation runtime never spends its recovery budget.
        # WHY: a handshake alone isn't recovery. Keep one deadline across flapping sockets;
        # a connection lasting a full recovery window earns a new budget and backoff.
        if self._deadline is None or stable:
            self._deadline = now + self.budget_s
            self.attempts = 0
        self._connected_at = None
        return self._deadline
