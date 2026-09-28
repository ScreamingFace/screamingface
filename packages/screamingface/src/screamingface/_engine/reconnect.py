"""Per-outage recovery accounting shared by both WebSocket transports."""

from dataclasses import dataclass

# WHY 2: the first re-login repairs an expired Access session; the second covers a login
# that raced a session refresh at the edge. A third challenge in a row means the edge will
# not accept this caller, and each prompt (up to 300 s) runs against the engine's 120 s
# orphan reaper while no client is attached (OME-1016 review fix 1).
_MAX_RECONNECT_CHALLENGES = 2


@dataclass
class _RecoveryWindow:
    budget_s: float
    attempts: int = 0
    _deadline: float | None = None
    _connected_at: float | None = None
    _challenges: int = 0

    def connected(self, now: float) -> None:
        self._connected_at = now
        self._challenges = 0

    def admit_challenge(self, now: float) -> float | None:
        """Admit one Access re-login in this outage: the seconds it may take, or None.

        INVARIANT: a re-login never outlives the outage budget, and at most
        `_MAX_RECONNECT_CHALLENGES` run back to back before the reconnect gives up.
        """
        self._challenges += 1
        if self._challenges > _MAX_RECONNECT_CHALLENGES:
            return None
        if self._deadline is None:
            return self.budget_s
        remaining = self._deadline - now
        return remaining if remaining > 0 else None

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
