"""When a run stops because the provider refuses the key, instead of failing every Case.

FEATURE (OME-1989): a run whose key the provider refuses cannot answer its next Case either.
Before this, each refusal became one failed Case and the run moved on: on 2026-11-19 one
account's 18 runs sent 7,056 calls that OpenRouter refused with 403, each back in about 0.3 s,
holding runner slots and loading the gateway the whole time. Now the run notices, sends nothing
more for the Candidate, and ends with one run-level error that names the cause.
STORY: as an on-call engineer, a disabled key ends its runs in a handful of calls, so one
account cannot queue everyone else behind thousands of calls that were never going to answer.

The rule, in the order the connector applies it to a Candidate call (the model or Fusion being
scored; a judge call is never counted and never refused here):

1. Before the call is sent: a run that has already stopped refuses it, with no gateway call.
2. An answer clears that model's count of refusals.
3. A refusal the gateway names ``auth_required`` (the provider rejected the key) or
   ``insufficient_credits`` (the key is out of credits) stops the run at once. Neither can
   succeed on the next Case.
4. Any other HTTP 403 is counted per model. The run stops when one model was refused with the
   same code on ``REFUSALS_BEFORE_STOP`` Cases in a row. A different refusal starts a new count.

WHY rule 4 counts Cases and waits: a provider can also answer 403 for ONE input (OpenRouter
does when its moderation flags a prompt), which is that Case's own failure. Stopping on the
first 403 would end healthy runs of a safety Benchmark. Several Attempts of one Case send the
same flagged input, so they count as one Case.

Worked example, ``REFUSALS_BEFORE_STOP = 5``, one model, a 100-Case run whose key was disabled:
Cases 1 to 5 are each refused 403 ``provider_error`` (5 gateway calls); the fifth stops the run;
Cases 6 to 100 are refused here with no gateway call; the run ends ``failed`` with
``provider_key_refused``. Had Case 3 been answered, the count would have restarted at Case 4.

WHY the remaining Cases are refused one by one rather than cancelled: url4 collects every
Case's error (``on_error="collect"``), so nothing raised inside one Case can stop its siblings.
Refusing each later call here costs no gateway call, and ``refused_key_scope`` then raises the
run-level error when the walk ends, so the stop is never folded into a finished Report.

INVARIANT: the state lives in a holder bound once per run (``refused_key_scope``), never on the
connector's handler, which one process may share between runs.
INVARIANT: the stop message is engine-authored fixed text plus the model id and a count. It
never carries the gateway's code or message, which are upstream input.
INVARIANT: this module never imports the url4 engine (``test_only_engine_extensions_import_url4``).
It raises its own ``KeyRefused``; the connector turns that into url4's ``ResolutionError``, as it
does for ``classification`` and ``attachment_parts``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final

from screamingface_engine.benchmarks.case_context import current_case_id
from screamingface_engine.candidate_scope import in_candidate_invocation

#: The run-level code of a run stopped by this rule. Engine-authored (``ENGINE_ERROR_CODES``).
STOP_CODE: Final[str] = "provider_key_refused"

#: How many Cases in a row one model must be refused 403, with the same code, before the run
#: stops. Small enough that a disabled key costs a handful of calls, large enough that a few
#: moderation-flagged inputs in a row do not end a healthy run.
REFUSALS_BEFORE_STOP: Final[int] = 5

_FORBIDDEN: Final[int] = 403
_KEY_REJECTED: Final[str] = "auth_required"
_OUT_OF_CREDITS: Final[str] = "insufficient_credits"


@dataclass
class _Streak:
    """One model's unbroken run of 403 refusals that all carried the same code."""

    code: str
    cases: set[str] = field(default_factory=set)
    # Refused calls that named no Case (a Candidate call outside a Benchmark's Case scope);
    # each counts as its own Case.
    uncased: int = 0

    @property
    def length(self) -> int:
        """How many Cases this streak covers."""
        return len(self.cases) + self.uncased


@dataclass
class _RunRefusals:
    """One run's refusal state: each model's streak, and the stop message once it stopped."""

    stop_message: str | None = None
    streaks: dict[str, _Streak] = field(default_factory=dict)


_RUN_REFUSALS: ContextVar[_RunRefusals | None] = ContextVar("refused_key_stop_run", default=None)


class KeyRefused(Exception):
    """The run stopped because the provider refuses its key; ``message`` is the stop message.

    The connector raises it to url4 as a permanent ``ResolutionError`` with ``STOP_CODE``
    (``key_refused_error``): permanent, because the same key is refused again.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


@contextmanager
def refused_key_scope() -> Iterator[None]:
    """Bind one run's refusal state, and end the run with the stop error if it stopped.

    WHY a fresh holder per run: url4's member tasks copy this context, so every call of the run
    sees the SAME holder object, and the state dies with the run.
    WHY the stop replaces an ``Exception`` but never a cancellation: once the run stopped, the
    refused key is the cause of whatever the walk raised next; a stop or deadline
    (``CancelledError``) is a different terminal reason and must stay itself.
    """
    refusals: _RunRefusals = _RunRefusals()
    token = _RUN_REFUSALS.set(refusals)
    try:
        yield
    except Exception as exc:
        if refusals.stop_message is not None:
            raise KeyRefused(refusals.stop_message) from exc
        raise
    else:
        if refusals.stop_message is not None:
            raise KeyRefused(refusals.stop_message)
    finally:
        _RUN_REFUSALS.reset(token)


def _candidate_refusals() -> _RunRefusals | None:
    """The run's holder when this call is a Candidate call of a run that binds one, else None."""
    return _RUN_REFUSALS.get() if in_candidate_invocation() else None


def refuse_if_stopped() -> None:
    """Rule 1: refuse a Candidate call of a run that already stopped, before anything is sent."""
    refusals: _RunRefusals | None = _candidate_refusals()
    if refusals is not None and refusals.stop_message is not None:
        raise KeyRefused(refusals.stop_message)


def note_answer(model: str, answer: str) -> str:
    """Rule 2: ``model`` answered a Candidate call, so its count of refusals starts over.

    Returns ``answer`` unchanged, so the connector notes the answer on the line that returns it.
    """
    refusals: _RunRefusals | None = _candidate_refusals()
    if refusals is not None:
        refusals.streaks.pop(model, None)
    return answer


def note_refusal(model: str, *, status: int, code: str) -> None:
    """Rules 3 and 4: count the gateway's refusal of a Candidate call, and stop the run if due.

    ``status`` is the gateway's HTTP status and ``code`` the code of its answer. The caller
    re-raises its own error either way, so the refused Case keeps its own failure.
    """
    refusals: _RunRefusals | None = _candidate_refusals()
    if refusals is None or refusals.stop_message is not None:
        return
    # Rule 3 — the key itself is rejected or out of credits: stop at once.
    refusals.stop_message = _key_refusal_message(model, code)
    if refusals.stop_message is not None:
        return
    # Rule 4 — any other 403: count Cases in a row for this model and this code.
    if status != _FORBIDDEN:
        refusals.streaks.pop(model, None)
        return
    streak: _Streak | None = refusals.streaks.get(model)
    if streak is None or streak.code != code:
        streak = refusals.streaks[model] = _Streak(code)
    if _add_current_case(streak) >= REFUSALS_BEFORE_STOP:
        refusals.stop_message = (
            f"The provider refused model {model} with HTTP 403 on {streak.length} Cases in a "
            "row. The key is disabled or may not use this model. The run was stopped."
        )


def _key_refusal_message(model: str, code: str) -> str | None:
    """The stop message when ``code`` says the key itself cannot work (rule 3), else None."""
    if code == _KEY_REJECTED:
        return (
            f"The provider rejected the key for model {model}. "
            "The run was stopped at the first rejected call."
        )
    if code == _OUT_OF_CREDITS:
        return (
            f"The provider reported that the key for model {model} is out of credits. "
            "The run was stopped at the first such call."
        )
    return None


def _add_current_case(streak: _Streak) -> int:
    """Add the Case being answered to ``streak``; the number of Cases it now covers."""
    case_id = current_case_id()
    if case_id is None:
        streak.uncased += 1
    else:
        streak.cases.add(str(case_id))
    return streak.length


__all__ = [
    "REFUSALS_BEFORE_STOP",
    "KeyRefused",
    "STOP_CODE",
    "note_answer",
    "note_refusal",
    "refuse_if_stopped",
    "refused_key_scope",
]
