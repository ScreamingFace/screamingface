"""Attempt facts of one logical model call: Engine attempts and Gateway upstream sends (C8).

FEATURE: Router Recipe extension (Unit 5.2). One logical model call may make several Engine HTTP
attempts (the transport/queue retry, the OME-1872 Candidate retry, a `max-age` re-issue), and the
Gateway reports the upstream sends behind each in `X-AIGW-Upstream-Attempts` (C7). An
`AttemptObserver` counts both at the transport seam without changing what the transport returns
or whether it retries. `observed_call` publishes the result once per call: to the recorder
channel for a call carrying `binding=`, and to the direct `/route-answer` invocation's private
scope for its `classifier` or `branch` role.

INVARIANT: unknown is never zero. A lost reply, a missing or unreadable header, or a header the
complete accounting contradicts makes `upstream_attempts` unknown; `possibly_billed` is false only
when every Engine attempt is known to have reached no provider.

INVARIANT: counters only. No request body, credential, header value or response is kept.
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from screamingface_engine.operation_calls import AttemptFact, record_attempt_fact
from screamingface_engine.world import gateway_transport

UPSTREAM_ATTEMPTS_HEADER = "x-aigw-upstream-attempts"

# WHY this exact grammar: C7 sends a bare non-negative decimal. A sign, a space, a fraction, a list
# or a non-ASCII digit is not one, and `int()` would accept several of those.
_COUNT = re.compile(r"0|[1-9][0-9]{0,9}")

Role = Literal["classifier", "branch"]


@dataclass(frozen=True, slots=True)
class Attempts:
    """The three C8 counters of one logical call."""

    engine_attempts: int
    upstream_attempts: int | None
    possibly_billed: bool


class AttemptObserver:
    """Counts the Engine HTTP attempts of one logical call and the upstream sends behind them."""

    __slots__ = ("_engine", "_last", "_reached", "_unknown", "_upstream")

    def __init__(self) -> None:
        self._engine = 0
        self._upstream = 0
        self._unknown = False
        self._reached = False
        self._last: int | None = None

    def answered(self, headers: Mapping[str, str], *, queue_refusal: bool) -> None:
        """One attempt the Gateway answered, with its response headers.

        WHY a queue refusal without a header reached no provider: the Gateway refuses it at
        admission, before any upstream send (`_queue_timeout`).
        """
        self._engine += 1
        count = _count(headers.get(UPSTREAM_ATTEMPTS_HEADER))
        self._last = count
        if count is None:
            self._unknown = True
            self._reached = self._reached or not queue_refusal
        else:
            self._upstream += count
            self._reached = self._reached or count > 0

    def lost(self, *, never_sent: bool) -> None:
        """One attempt with no response; ``never_sent`` for a connect-phase failure."""
        self._engine += 1
        self._last = None
        self._unknown = True
        self._reached = self._reached or not never_sent

    def check_accounting(self, aigw: object) -> None:
        """Cross-check the last header against a live chat success's `_aigw` accounting.

        WHY only complete accounting with nothing omitted: partial or bounded accounting cannot
        verify the header independently, and a list length alone proves no mismatch (C7).
        """
        sends = _accounted_sends(aigw)
        if sends is not None and self._last is not None and sends != self._last:
            self._unknown = True
            self._reached = True

    def attempts(self) -> Attempts | None:
        """The counters, or ``None`` when no attempt was initiated (a local refusal)."""
        if self._engine == 0:
            return None
        upstream = None if self._unknown else self._upstream
        billed = self._reached if upstream is None else upstream > 0
        return Attempts(self._engine, upstream, billed)


def _count(value: str | None) -> int | None:
    return int(value) if value is not None and _COUNT.fullmatch(value) else None


def _accounted_sends(aigw: object) -> int | None:
    """`sum(1 + redirect_hop_count)` of complete accounting with no omitted attempt, else None.

    WHY `usage_accounting`: the Gateway's `_aigw` block names it so (`world/accounting.py`
    `read_aigw`); C7 writes the same object as `_aigw.accounting`.
    """
    accounting = aigw.get("usage_accounting") if isinstance(aigw, Mapping) else None
    attempts = accounting.get("attempts") if isinstance(accounting, Mapping) else None
    if not (
        isinstance(accounting, Mapping)
        and accounting.get("capture_status") == "complete"
        and _whole(accounting.get("omitted_attempts")) == 0
        and isinstance(attempts, list)
    ):
        return None
    hops = [_whole(a.get("redirect_hop_count")) for a in attempts if isinstance(a, Mapping)]
    known = [hop for hop in hops if hop is not None]
    return sum(1 + hop for hop in known) if len(known) == len(attempts) else None


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


# --- the direct `/route-answer` invocation's private scope ----------------------------------------


@dataclass(slots=True)
class _DirectScope:
    facts: dict[str, AttemptFact] = field(default_factory=dict)
    closed: bool = False


_direct: contextvars.ContextVar[_DirectScope | None] = contextvars.ContextVar(
    "screamingface_engine_direct_attempts", default=None
)
_role: contextvars.ContextVar[Role | None] = contextvars.ContextVar(
    "screamingface_engine_direct_attempt_role", default=None
)


def _direct_sink(facts: Mapping[str, AttemptFact]) -> None:
    """Receives a direct scope's facts when it closes; tests replace it. Keeps nothing.

    WHY a sink and no reader: the direct entry has no JOIN and no public field for them (C8).
    """
    del facts


@contextmanager
def direct_attempts() -> Iterator[None]:
    """One direct `/route-answer` invocation's private scope with `classifier`/`branch` slots.

    INVARIANT: visible to nested dispatch (a context variable), never to a concurrent invocation
    (each runs in its own context); closed on success, failure and cancellation, after which no
    write lands.
    """
    scope = _DirectScope()
    token = _direct.set(scope)
    try:
        yield
    finally:
        _direct.reset(token)
        scope.closed = True
        _direct_sink(dict(scope.facts))


@contextmanager
def direct_role(role: Role) -> Iterator[None]:
    """Mark the model call made inside as the direct invocation's ``role``."""
    token = _role.set(role)
    try:
        yield
    finally:
        _role.reset(token)


@contextmanager
def observed_call(binding: str | None) -> Iterator[AttemptObserver | None]:
    """An observer for one logical model call, published once when the call ends.

    Yields ``None`` for a call with no ``binding`` outside a direct role, which then runs
    exactly as before.

    WHY no fact on cancellation: a cancelled call neither answered nor failed, and its reader is
    cancelled with it. WHY none without an attempt: a local refusal sent nothing.
    """
    scope, role = _direct.get(), _role.get()
    direct = scope if role is not None else None
    if binding is None and direct is None:
        yield None
        return
    observer = AttemptObserver()
    try:
        yield observer
    except Exception as exc:
        _publish(observer, binding, direct, role, failure=exc)
        raise
    _publish(observer, binding, direct, role, failure=None)


def _publish(
    observer: AttemptObserver,
    binding: str | None,
    direct: _DirectScope | None,
    role: Role | None,
    *,
    failure: Exception | None,
) -> None:
    attempts = observer.attempts()
    if attempts is None:
        return
    status: Literal["answered", "failed"] = "answered" if failure is None else "failed"
    code = None if failure is None else _code(failure)
    counters = (attempts.engine_attempts, attempts.upstream_attempts, attempts.possibly_billed)
    if binding is not None:
        record_attempt_fact(AttemptFact(binding, status, code, *counters))
    if direct is not None and role is not None and not direct.closed:
        direct.facts[role] = AttemptFact(role, status, code, *counters)


def _code(failure: Exception) -> str | None:
    """The failure's Engine code; a Gateway refusal's is its status code, never its body's.

    INVARIANT (C11): a refusal after a classifier or branch POST has origin
    `aigateway_http_<status>`, so a lifted body code (or a spoofed Router code) never stands in
    a fact, as it never stands in a routed answer (`gateway_endpoints._relayed`).
    """
    if isinstance(failure, gateway_transport._GatewayRefusal):
        return f"aigateway_http_{failure.status}"
    code = getattr(failure, "code", None)
    return None if code is None else str(code)


__all__ = [
    "UPSTREAM_ATTEMPTS_HEADER",
    "AttemptObserver",
    "Attempts",
    "Role",
    "direct_attempts",
    "direct_role",
    "observed_call",
]
