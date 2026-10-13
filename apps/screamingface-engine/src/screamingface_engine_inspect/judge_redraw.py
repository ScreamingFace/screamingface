# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Ask the judge again when its reply doesn't parse — the one redraw loop Task scorers share.

FEATURE (OME-1527 R3): a judge reply with no verdict word is still a SUCCESSFUL model
call, so nothing below a scorer retries it. Without this helper a Task scorer has two bad
options: raise, and the whole Case fails as ``scorer_error`` (wasting its other judge
calls), or default the item to "not met", a silently wrong score.

The same budget also covers a judge call the gateway failed for a moment (a 429 or 5xx),
because the hand-built boards' ``;retry=2`` retried those too and a migrated Benchmark must
not lose a Case to one blip.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from inspect_ai.model import ChatMessage, GenerateConfig, Model, ModelOutput

from screamingface_engine_inspect.judge_provider import JudgeReplyBlank, fresh_judge_draw

#: How many times an item may be asked AGAIN after an unparseable first reply. Matches the
#: hand-built boards' ``;retry=2`` (``JUDGE_RETRIES``), so a migrated Benchmark's judge gets
#: the same three draws per item it had before.
MAX_JUDGE_REDRAWS: Final[int] = 2

#: How much of the last reply the error quotes — enough to see why it failed, no more.
_REPLY_HEAD_CHARS: Final[int] = 200

#: The wait before re-asking after a temporary gateway failure, url4's guard backoff
#: (``url4/dag/nodes/guard.py``, Spec C §13.3) so a migrated board waits as it did:
#: retry k waits ``0.5 s * 2^(k-1)`` plus up to 0.5 s of jitter, never more than 30 s,
#: and at least what the gateway's ``Retry-After`` asked for.
_BACKOFF_BASE_S: Final[float] = 0.5
_BACKOFF_JITTER_S: Final[float] = 0.5
_BACKOFF_CAP_S: Final[float] = 30.0

# Seams, so tests neither wait the backoff out nor depend on the global random state.
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
_jitter: Callable[[float, float], float] = random.uniform


class JudgeReplyUnparseable(RuntimeError):
    """The judge never gave a parseable reply for one item; the Case fails as
    ``judge_reply_invalid`` (the scorer adapter maps it), blaming the judge, not our code."""


def _is_temporary(exc: Exception) -> bool:
    """Whether a failed judge call is a passing gateway fault worth asking again.

    The connector raises a 429 or 5xx as an error with ``permanent=False`` (``world/
    connector.py`` ``_raise_for_status``); url4's ``;retry=`` retries exactly those. Read
    duck-typed, as url4's executor does, because this lane may not import the url4 engine.
    Anything without that mark (a refused config, a 4xx, our own bug) is not temporary.
    """

    return getattr(exc, "permanent", None) is False


def _backoff_wait(retry: int, exc: Exception) -> float:
    """The wait before ``retry`` (1-based): url4's backoff, raised to ``Retry-After``."""

    delay: float = _BACKOFF_BASE_S * 2 ** (retry - 1) + _jitter(0, _BACKOFF_JITTER_S)
    retry_after: object = getattr(exc, "retry_after", None)
    asked: float = float(retry_after) if isinstance(retry_after, int | float) else 0.0
    return max(min(delay, _BACKOFF_CAP_S), asked)


@dataclass(frozen=True, slots=True)
class JudgedItem[Verdict]:
    """One judged item: the parsed verdict and how many redraws it took (0 = first ask).

    ``redraws`` is what a scorer puts in ``Score.metadata`` to feed ``judge_invalid_replies``.
    It counts unparseable replies only; a re-ask after a temporary gateway failure is not one.
    """

    verdict: Verdict
    redraws: int


async def judge_until_parsed[Verdict](
    judge: Model,
    prompt: str | list[ChatMessage],
    parse: Callable[[str], Verdict | None],
    *,
    item: str,
    judge_pass: int | None = None,
) -> JudgedItem[Verdict]:
    """Ask the judge about one item, and ask again while its reply won't parse.

    Think of it as an examiner whose handwriting is sometimes illegible: you hand the same
    question back for a fresh answer, a bounded number of times, and if it stays illegible
    you report THAT, by name, instead of guessing the mark.

    Stages, in execution order:

    1. Ask: send ``prompt`` with inspect's cache off (``cache=False``), so an eval-level
       ``GenerateConfig(cache=True)`` can't replay a reply. The first ask otherwise behaves
       like any judge call, AI Gateway cache included. With ``judge_pass``, every draw
       names that pass, so the provider sends the pass's seed (OME-1527 R12).
    2. Parse: ``parse`` returns the verdict, or ``None`` when the reply is unparseable. A
       blank reply never reaches ``parse``: the provider refuses it as
       :class:`JudgeReplyBlank`, which counts here as unparseable too.
    3. Re-ask, from the same budget of ``MAX_JUDGE_REDRAWS`` (the hand-built ``;retry=2``):
       a. after an unparseable reply, a REDRAW inside :func:`fresh_judge_draw`, which makes
          the gateway skip its exact-request cache. Gotcha: the redraw is the SAME bytes as
          the first ask, so without the opt-out the cache would hand back the same broken
          text. A redraw inside pass ``k`` keeps pass ``k``'s seed: only the cache policy
          changes. Once a reply failed to parse, every later ask stays fresh, because the cache
          still holds that broken reply. Limit: a judge pinned at ``temperature=0`` can send
          the same bad reply again; redrawing pays off when the judge samples.
       b. after a temporary gateway failure (429 or 5xx, ``permanent=False``), a RETRY after
          url4's backoff, keeping the cache unless a reply already failed to parse: the
          failure stored nothing, so the cache can't echo it, and an opt-out would stop the
          good reply from being stored for cache-backed replays. Any other failed call
          propagates at once, never re-asked.
    4. Give up: when the budget is spent on an unparseable reply, raise
       :class:`JudgeReplyUnparseable` naming ``item`` and quoting the last reply's head; the
       scorer adapter turns it into the Case's ``judge_reply_invalid``, never "not met".
       When it is spent on a temporary failure, that failure propagates as it came.

    Worked example (``MAX_JUDGE_REDRAWS = 2``, so at most 3 asks): replies
    ``["Let me think...", "MET"]`` → ask 1 unparseable, ask 2 parses → returns
    ``JudgedItem(verdict=True, redraws=1)``. ``[502, "MET"]`` → ask 1 fails for a moment,
    wait ~0.5-1 s, ask 2 (cache kept) parses → ``JudgedItem(verdict=True, redraws=0)``.
    ``["...", "...", "..."]`` → three asks, no verdict → raises, and no fourth call is made.

    Args:
        judge: the inspect model to ask; on the plugin lane, the gateway judge provider.
        prompt: the item's grader prompt, a string or chat messages, the same every draw.
        parse: reply text → verdict; ``None`` means "no verdict in this reply". It must not
            raise for a merely malformed reply, or the item fails without a redraw.
        item: names the item in the error (e.g. ``"case 7 rubric r2"``).
        judge_pass: the judge pass this item belongs to, sent as ``GenerateConfig(seed=k)``
            on every draw; only a row declaring ``JudgeSpec(seed_per_pass=True)`` admits it.
            ``None`` (the default) sends no seed, as before.

    Returns:
        The parsed verdict and the number of redraws it took.

    Raises:
        JudgeReplyUnparseable: no parseable reply after ``MAX_JUDGE_REDRAWS`` re-asks.
        Exception: a judge call that failed for good, or for a moment on the last ask.
    """

    reply: str = ""
    config: GenerateConfig = GenerateConfig(seed=judge_pass)
    unparseable: int = 0
    for ask in range(1 + MAX_JUDGE_REDRAWS):
        # Stage 1 / 3a — ask; once a reply failed to parse, every ask leaves the gateway cache.
        try:
            if unparseable:
                with fresh_judge_draw():
                    output: ModelOutput = await judge.generate(prompt, config=config, cache=False)
            else:
                output = await judge.generate(prompt, config=config, cache=False)
        except JudgeReplyBlank:
            # Stage 2 — a blank reply has no verdict: unparseable, so it costs a redraw.
            reply = ""
            unparseable += 1
            continue
        except Exception as exc:
            # Stage 3b — a passing gateway fault is asked again after a wait; anything else,
            # or a fault on the last ask, propagates as it came.
            if not _is_temporary(exc) or ask == MAX_JUDGE_REDRAWS:
                raise
            await _sleep(_backoff_wait(ask + 1, exc))
            continue
        reply = output.completion
        # Stage 2 — parse; a verdict ends the loop.
        verdict: Verdict | None = parse(reply)
        if verdict is not None:
            return JudgedItem(verdict=verdict, redraws=unparseable)
        unparseable += 1
    # Stage 4 — the budget is spent on an unparseable reply: fail by name, never "not met".
    raise JudgeReplyUnparseable(
        f"the judge gave no parseable reply for {item} after {MAX_JUDGE_REDRAWS} redraws; "
        f"last reply: {reply[:_REPLY_HEAD_CHARS]!r}"
    )


__all__ = ["MAX_JUDGE_REDRAWS", "JudgeReplyUnparseable", "JudgedItem", "judge_until_parsed"]
