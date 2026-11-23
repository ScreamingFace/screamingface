"""When a run stops because the provider refuses the key, instead of failing every Case.

FEATURE (OME-1989): a run whose key the provider refuses cannot answer its next Case either.
Before this, each refusal became one failed Case and the run moved on: on 2026-11-19 one
account's 18 runs sent 7,056 calls that OpenRouter refused with 403, each back in about 0.3 s,
holding runner slots and loading the gateway the whole time. Now the run notices, sends nothing
more for the Candidate, and ends with one run-level error that names the cause.
STORY: as an on-call engineer, a disabled key ends its runs in a handful of calls, so one
account cannot queue everyone else behind thousands of calls that were never going to answer.

The rule judges CASES, never single calls. A Candidate can survive a refused call: a quorum
Fusion drops a failed optional member, a fallback Gate answers with another recipe, and a row
policy (``on_error=collect``) keeps the other rows. So a refused call only matters when the
Case it belongs to fails BECAUSE of it. The Candidate adapter opens ``watch_case_refusals``
around each Case's Candidate invocation; the connector records into it what each model call met
(``note_refusal``, ``note_answer``); the Case is settled when the invocation ends:

1. Before the Case starts: a run that has already stopped refuses it, with no gateway call.
2. The Case answered, and its last round trip was LIVE: the key works, so every count restarts.
   A Case answered only from the gateway's cache or a frozen copy proves nothing about the key,
   so it neither counts nor restarts the counts.
3. A key refusal caused the Case to go unanswered: no call of the Case answered at all (every
   member of a quorum refused, which fails as ``quorum_not_met``; or a row policy collected
   every row's refusal), or the Case failed with the refusal's own code (a refused synthesiser
   or solo model while other calls answered). Then:
   a. a refusal the gateway names ``auth_required`` (the provider rejected the key) or
      ``insufficient_credits`` (the key is out of credits) stops the run at once;
   b. an HTTP 403 adds the Case to that model's count; the run stops when one model was refused
      with the same code on ``REFUSALS_BEFORE_STOP`` Cases in a row. A different code starts a
      new count.
4. Any other Case (failed for another reason, or answered only from a recording) leaves every
   count as it was.

WHY 3b counts Cases and waits: a provider can also answer 403 for ONE input (OpenRouter does
when its moderation flags a prompt), which is that Case's own failure. Stopping on the first 403
would end healthy runs of a safety Benchmark. Several Attempts of one Case send the same flagged
input, so they count as one Case.

Worked example, ``REFUSALS_BEFORE_STOP = 5``, a 100-Case run:
- Solo model, key disabled: Cases 1 to 5 each fail 403 ``provider_error`` (5 gateway calls); the
  fifth stops the run; Cases 6 to 100 are refused at rule 1 with no gateway call; the run ends
  ``failed`` with ``provider_key_refused``. Had Case 3 answered live, the count would have
  restarted at Case 4.
- Quorum Fusion (quorum 2 of 3) whose optional member's key is out of credits: every Case is
  answered by the other two members and the synthesiser (rule 2), so the run never stops and
  scores all 100 Cases. Had the synthesiser's key been out of credits instead, Case 1 would
  fail ``insufficient_credits`` and stop the run (rule 3a).

WHY the remaining Cases are refused one by one rather than cancelled: url4 collects every
Case's error (``on_error="collect"``), so nothing raised inside one Case can stop its siblings.
Refusing each later Case here costs no gateway call, and ``refused_key_scope`` then raises the
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

from screamingface_engine.benchmarks.case_context import CaseId
from screamingface_engine.world.reply_origin import watch_reply_origin

#: The run-level code of a run stopped by this rule. Engine-authored (``ENGINE_ERROR_CODES``).
STOP_CODE: Final[str] = "provider_key_refused"

#: How many Cases in a row one model must be refused 403, with the same code, before the run
#: stops. Small enough that a disabled key costs a handful of calls, large enough that a few
#: moderation-flagged inputs in a row do not end a healthy run.
REFUSALS_BEFORE_STOP: Final[int] = 5

_FORBIDDEN: Final[int] = 403
_KEY_REJECTED: Final[str] = "auth_required"
_OUT_OF_CREDITS: Final[str] = "insufficient_credits"
_KEY_CODES: Final[frozenset[str]] = frozenset({_KEY_REJECTED, _OUT_OF_CREDITS})


class KeyRefused(Exception):
    """The run stopped because the provider refuses its key; ``message`` is the stop message.

    The connector raises it to url4 as a permanent ``ResolutionError`` with ``STOP_CODE``
    (``key_refusal_as_url4_error``): permanent, because the same key is refused again.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


@dataclass(frozen=True, slots=True)
class _Refusal:
    """One key refusal a model call met: the model, the gateway's HTTP status and its code."""

    model: str
    status: int
    code: str


@dataclass
class _CaseCalls:
    """What one Case's Candidate calls met: their key refusals, and whether any call answered."""

    refusals: list[_Refusal] = field(default_factory=list)
    answered: bool = False


@dataclass
class _Streak:
    """One model's unbroken run of failed Cases, all refused 403 with the same code."""

    code: str
    cases: set[str] = field(default_factory=set)
    # Candidate invocations that named no Case; each counts as its own Case.
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
_CASE_CALLS: ContextVar[_CaseCalls | None] = ContextVar("refused_key_stop_case", default=None)


@contextmanager
def refused_key_scope() -> Iterator[None]:
    """Bind one run's refusal state, and end the run with ``KeyRefused`` if it stopped.

    WHY a fresh holder per run: url4's member tasks copy this context, so every Case of the run
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


@contextmanager
def watch_case_refusals(case_id: CaseId | None) -> Iterator[None]:
    """Watch one Case's Candidate invocation, and settle the run's counts when it ends.

    Opened by the Candidate adapter around the invocation. Outside a run (the sync surface,
    direct runs) no holder is bound and this watches nothing.
    WHY a cancellation settles nothing: a stopped or timed-out Case says nothing about the key.
    """
    refusals: _RunRefusals | None = _RUN_REFUSALS.get()
    if refusals is None:
        yield
        return
    # Rule 1 — the run already stopped: refuse the Case before anything is sent.
    if refusals.stop_message is not None:
        raise KeyRefused(refusals.stop_message)
    calls: _CaseCalls = _CaseCalls()
    token = _CASE_CALLS.set(calls)
    try:
        with watch_reply_origin() as origin:
            yield
    except Exception as exc:
        _settle_case(refusals, calls, case_id, failure_code=getattr(exc, "code", None))
        raise
    else:
        _settle_case(refusals, calls, case_id, failure_code=None, live=origin.origin == "live")
    finally:
        _CASE_CALLS.reset(token)


def note_answer(model: str, answer: str) -> str:
    """Record that a model call of the current Case answered (from any origin).

    Returns ``answer`` unchanged, so the connector notes the answer on the line that returns it.
    ``model`` names the call for the reader; a Case's answers are not told apart by model.
    """
    del model
    calls: _CaseCalls | None = _CASE_CALLS.get()
    if calls is not None:
        calls.answered = True
    return answer


def note_refusal(model: str, *, status: int, code: str) -> None:
    """Record a key refusal the gateway gave a model call of the current Case.

    ``status`` is the gateway's HTTP status and ``code`` the code of its answer. Only a refusal
    that can mean the key (``auth_required``, ``insufficient_credits``, any 403) is kept; the
    caller re-raises its own error either way, so the call keeps its own failure.
    """
    calls: _CaseCalls | None = _CASE_CALLS.get()
    if calls is not None and (code in _KEY_CODES or status == _FORBIDDEN):
        calls.refusals.append(_Refusal(model, status, code))


def _settle_case(
    refusals: _RunRefusals,
    calls: _CaseCalls,
    case_id: CaseId | None,
    *,
    failure_code: object,
    live: bool = False,
) -> None:
    """Rules 2 to 4: settle one ended Case into the run's counts.

    ``failure_code`` is the code the Case failed with (None when it answered); ``live`` says the
    answered Case's last round trip reached the provider.
    """
    if refusals.stop_message is not None:
        return
    # Rule 2 — answered, and the last round trip was live: the key works.
    if failure_code is None and calls.answered and live:
        refusals.streaks.clear()
        return
    refusals.stop_message = _stop_message(refusals.streaks, _causes(calls, failure_code), case_id)


def _causes(calls: _CaseCalls, failure_code: object) -> list[_Refusal]:
    """Rule 3's test: the refusals that left this Case unanswered; empty means rule 4.

    A dict keeps the first-seen order and drops a model's repeated refusals within the Case.
    """
    return list(
        dict.fromkeys(
            refusal
            for refusal in calls.refusals
            if refusal.code == failure_code or not calls.answered
        )
    )


def _stop_message(
    streaks: dict[str, _Streak], causes: list[_Refusal], case_id: CaseId | None
) -> str | None:
    """Rules 3a and 3b: count this Case's causing refusals; the stop message once one is due."""
    # Rule 3a — the key itself is rejected or out of credits: stop at once.
    for refusal in causes:
        message: str | None = _key_refusal_message(refusal)
        if message is not None:
            return message
    # Rule 3b — a 403: count this Case for each refused model, per code.
    for refusal in causes:
        streak: _Streak | None = streaks.get(refusal.model)
        if streak is None or streak.code != refusal.code:
            streak = streaks[refusal.model] = _Streak(refusal.code)
        _add_case(streak, case_id)
        if streak.length >= REFUSALS_BEFORE_STOP:
            return (
                f"The provider refused model {refusal.model} with HTTP 403 on {streak.length} "
                "Cases in a row. The key is disabled or may not use this model. "
                "The run was stopped."
            )
    return None


def _key_refusal_message(refusal: _Refusal) -> str | None:
    """The stop message when ``refusal`` says the key itself cannot work (rule 3a), else None."""
    if refusal.code == _KEY_REJECTED:
        return (
            f"The provider rejected the key for model {refusal.model}. "
            "The run was stopped at the first Case it failed."
        )
    if refusal.code == _OUT_OF_CREDITS:
        return (
            f"The provider reported that the key for model {refusal.model} is out of credits. "
            "The run was stopped at the first Case it failed."
        )
    return None


def _add_case(streak: _Streak, case_id: CaseId | None) -> None:
    """Add one failed Case to ``streak``; an Attempt of a Case already in it adds nothing."""
    if case_id is None:
        streak.uncased += 1
    else:
        streak.cases.add(str(case_id))


__all__ = [
    "REFUSALS_BEFORE_STOP",
    "STOP_CODE",
    "KeyRefused",
    "note_answer",
    "note_refusal",
    "refused_key_scope",
    "watch_case_refusals",
]
