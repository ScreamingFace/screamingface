"""The internal evidence of one capture scope: attempt facts, call outcomes and Router steps.

FEATURE: Router Recipe extension (Unit 5.2, contracts C4, C8). Beside the operation-call
recorders, `capture_operation_calls` opens one provenance channel that holds three kinds of
evidence no projection, report, accounting or wire field reads:

- an **attempt fact** per bound logical model call (C8: what its HTTP attempts did);
- a **call outcome** per bound logical call: answered with its reply text, failed with its code
  and permanence, or cancelled, published at the operation boundary even when no HTTP attempt was
  made;
- the **step document** of each Router ADMIT and DECIDE, once per step and occurrence binding;
- the **claim** of each Router step (ADMIT, CLASSIFY, DECIDE, JOIN), once per step and binding.

WHY a channel of its own: `OperationCall` and every projection of it stay unchanged, and a later
Router step can prove that its context is what an earlier step of this occurrence produced.
INVARIANT: facts and call outcomes reach every active scope (isolated alike, as the recorders);
step documents and claims live in the innermost scope only. All are single assignment: a second
claim or step document for one step and binding, identical or not, is refused, and a second outcome
for one binding never replaces the first but makes that binding's outcome ambiguous, which a Router
step refuses.
INVARIANT: no request body, credential or header is kept; a call outcome keeps the reply text
the operation-call recorder keeps anyway, for the same scope and lifetime.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

Step = Literal["admit", "decide"]
"""A Router step that records its document for later steps to prove against."""
RouterStep = Literal["admit", "classify", "decide", "join"]
"""A Router step that runs at most once per binding and scope."""
CallStatus = Literal["answered", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class AttemptFact:
    """What the HTTP attempts of one bound logical model call did (C8); counters only.

    INVARIANT: ``upstream_attempts`` is ``None`` when unknown, never zero; ``possibly_billed`` is
    false only when every Engine attempt is known to have reached no provider.
    """

    binding: str
    status: Literal["answered", "failed"]
    code: str | None
    engine_attempts: int
    upstream_attempts: int | None
    possibly_billed: bool

    def document(self) -> dict[str, object]:
        """The C8 attempt-fact shape."""
        return {
            "binding": self.binding,
            "status": self.status,
            "code": self.code,
            "engine_attempts": self.engine_attempts,
            "upstream_attempts": self.upstream_attempts,
            "possibly_billed": self.possibly_billed,
        }


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """How one bound logical call ended at its operation boundary.

    ``output`` is what the call returned: the reply of an answered call, a scoring
    classification's failure document, ``""`` for a failed model call. ``code`` and ``permanent``
    are what a failure carried to its url4 error row (``None`` when it carried none), so the row
    can be checked against them. A cancelled call (a control-plane ending) left no row at all.
    """

    binding: str
    path: str
    status: CallStatus
    output: str = ""
    code: str | None = None
    permanent: bool | None = None


class ProvenanceConflict(ValueError):
    """Evidence written twice: a Router step document, or the outcome of one bound call."""


@dataclass(slots=True)
class _Channel:
    facts: list[AttemptFact] = field(default_factory=list[AttemptFact])
    calls: dict[str, CallOutcome] = field(default_factory=dict[str, CallOutcome])
    ambiguous: set[str] = field(default_factory=set[str])
    steps: dict[tuple[Step, str], str] = field(default_factory=dict[tuple[Step, str], str])
    claimed: set[tuple[RouterStep, str]] = field(default_factory=set[tuple[RouterStep, str]])


_channels: contextvars.ContextVar[tuple[_Channel, ...]] = contextvars.ContextVar(
    "screamingface_engine_operation_provenance", default=()
)


@contextmanager
def open_provenance(*, isolated: bool) -> Iterator[None]:
    """Open this capture scope's channel; `capture_operation_calls` calls it, isolated alike."""
    channel = _Channel()
    token = _channels.set((channel,) if isolated else (*_channels.get(), channel))
    try:
        yield
    finally:
        _channels.reset(token)


def provenance_open() -> bool:
    """Whether a capture scope is active, so a Router step can record and verify."""
    return bool(_channels.get())


# --- attempt facts (C8) ---------------------------------------------------------------------------


def record_attempt_fact(fact: AttemptFact) -> None:
    """Publish one bound call's attempt fact to every active scope; a no-op outside every scope."""
    for channel in _channels.get():
        channel.facts.append(fact)


def current_attempt_facts() -> tuple[AttemptFact, ...] | None:
    """A snapshot of the INNERMOST active scope's attempt facts, or None outside every scope."""
    active = _channels.get()
    return tuple(active[-1].facts) if active else None


def latest_attempt_fact(binding: str) -> AttemptFact | None:
    """The newest attempt fact for ``binding`` in the INNERMOST active scope, or None.

    WHY the newest: JOIN (C4) reads the latest fact per binding, as it reads the latest call.
    """
    active = _channels.get()
    if not active:
        return None
    return next((fact for fact in reversed(active[-1].facts) if fact.binding == binding), None)


# --- call outcomes --------------------------------------------------------------------------------


def ended(binding: str, path: str, failure: BaseException, output: str = "") -> CallOutcome:
    """The outcome of a call that ended with ``failure``.

    A cancellation is ``cancelled``; any other failure keeps exactly what url4 writes into the
    call's error row (`_error_payload`): a non-empty string ``code`` and a boolean ``permanent``,
    never the message.
    """
    if isinstance(failure, asyncio.CancelledError):
        return CallOutcome(binding, path, "cancelled")
    code = getattr(failure, "code", None)
    permanent = getattr(failure, "permanent", None)
    return CallOutcome(
        binding,
        path,
        "failed",
        output,
        code=str(code) if isinstance(code, str) and code else None,
        permanent=permanent if isinstance(permanent, bool) else None,
    )


async def outcome_of(binding: object, path: str, answer: Awaitable[str]) -> str:
    """Await one endpoint call and, for a bound call, publish how it ended.

    INVARIANT (C8, C11): every terminal bound call publishes one outcome: its reply, its failure
    (one that made no HTTP attempt included) or its cancellation, so a Router step proves a row by
    its call. An unbound call is awaited unchanged; the outcome never changes what propagates.
    """
    if not isinstance(binding, str):
        return await answer
    try:
        reply = await answer
    except (Exception, asyncio.CancelledError) as failure:
        record_call_outcome(ended(binding, path, failure))
        raise
    record_call_outcome(CallOutcome(binding, path, "answered", reply))
    return reply


def record_call_outcome(outcome: CallOutcome) -> None:
    """Publish one bound call's terminal outcome to every active scope; a no-op outside them.

    INVARIANT: single assignment. A second outcome for a binding in a scope never replaces the
    first; it makes the binding ambiguous there (one logical call per Router binding and scope).
    """
    for channel in _channels.get():
        if outcome.binding in channel.calls:
            channel.ambiguous.add(outcome.binding)
        else:
            channel.calls[outcome.binding] = outcome


def call_outcome(binding: str) -> CallOutcome | None:
    """The outcome ``binding``'s call recorded in the INNERMOST active scope, or None.

    Raises:
        ProvenanceConflict: the binding ended more than once in that scope.
    """
    active = _channels.get()
    if not active:
        return None
    channel = active[-1]
    if binding in channel.ambiguous:
        raise ProvenanceConflict("a bound call ended twice in one scope")
    return channel.calls.get(binding)


# --- Router step documents ------------------------------------------------------------------------


def canonical_document(value: object) -> str:
    """The canonical text of one strict JSON value: sorted keys, compact, type-exact.

    WHY text and not the value: Python equality makes ``1 == 1.0 == True``; their JSON texts
    differ, so two documents compare equal only when their values and types do.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def claim_step(step: RouterStep, binding: str) -> None:
    """Claim this scope's one execution of ``step`` for ``binding``, before the step does any work.

    INVARIANT: synchronous and called before the step's first await, read, provider call or
    publication, so of two executions (sequential, or concurrent in one event loop) exactly one
    claims and the other refuses before any effect. Outside every scope nothing is claimed: there a
    Router step reads nothing, calls nothing and publishes nothing (C4 `router_unsupported`).

    Raises:
        ProvenanceConflict: the innermost scope already claimed that step for that binding.
    """
    active = _channels.get()
    if not active:
        return
    claimed = active[-1].claimed
    if (step, binding) in claimed:
        raise ProvenanceConflict(f"router {step} ran twice for one binding")
    claimed.add((step, binding))


def record_step(step: Step, binding: str, value: object) -> None:
    """Keep ``value`` as this scope's ``step`` document for ``binding``, exactly once.

    Raises:
        ProvenanceConflict: the innermost scope already holds a document for that step and
            binding (one execution per Router step and binding in a scope), or no scope is open.
    """
    active = _channels.get()
    if not active:
        raise ProvenanceConflict(f"router {step} runs outside a capture scope")
    steps = active[-1].steps
    if (step, binding) in steps:
        raise ProvenanceConflict(f"router {step} ran twice for one binding")
    steps[(step, binding)] = canonical_document(value)


def recorded_step(step: Step, binding: str) -> str | None:
    """The canonical ``step`` document this scope recorded for ``binding``, or None."""
    active = _channels.get()
    return active[-1].steps.get((step, binding)) if active else None


__all__ = [
    "AttemptFact",
    "CallOutcome",
    "CallStatus",
    "ProvenanceConflict",
    "RouterStep",
    "Step",
    "call_outcome",
    "canonical_document",
    "claim_step",
    "current_attempt_facts",
    "ended",
    "latest_attempt_fact",
    "open_provenance",
    "outcome_of",
    "provenance_open",
    "record_attempt_fact",
    "record_call_outcome",
    "record_step",
    "recorded_step",
]
