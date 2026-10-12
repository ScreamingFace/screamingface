# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on.
"""Ask the judge again when its reply doesn't parse — the one redraw loop Task scorers share.

FEATURE (OME-1527 R3): a judge reply with no verdict word is still a SUCCESSFUL model
call, so nothing below a scorer retries it. Without this helper a Task scorer has two bad
options: raise, and the whole Case fails as ``scorer_error`` (wasting its other judge
calls), or default the item to "not met", a silently wrong score.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from inspect_ai.model import ChatMessage, Model, ModelOutput

from screamingface_engine_inspect.judge_provider import JudgeReplyBlank, fresh_judge_draw

#: How many times an item may be asked AGAIN after an unparseable first reply. Matches the
#: hand-built boards' ``;retry=2`` (``JUDGE_RETRIES``), so a migrated Benchmark's judge gets
#: the same three draws per item it had before.
MAX_JUDGE_REDRAWS: Final[int] = 2

#: How much of the last reply the error quotes — enough to see why it failed, no more.
_REPLY_HEAD_CHARS: Final[int] = 200


class JudgeReplyUnparseable(RuntimeError):
    """The judge never gave a parseable reply for one item; the Case fails as
    ``judge_reply_invalid`` (the scorer adapter maps it), blaming the judge, not our code."""


@dataclass(frozen=True, slots=True)
class JudgedItem[Verdict]:
    """One judged item: the parsed verdict and how many redraws it took (0 = first ask).

    ``redraws`` is what a scorer puts in ``Score.metadata`` to feed ``judge_invalid_replies``.
    """

    verdict: Verdict
    redraws: int


async def judge_until_parsed[Verdict](
    judge: Model,
    prompt: str | list[ChatMessage],
    parse: Callable[[str], Verdict | None],
    *,
    item: str,
) -> JudgedItem[Verdict]:
    """Ask the judge about one item, and ask again while its reply won't parse.

    Think of it as an examiner whose handwriting is sometimes illegible: you hand the same
    question back for a fresh answer, a bounded number of times, and if it stays illegible
    you report THAT, by name, instead of guessing the mark.

    Stages, in execution order:

    1. Ask: send ``prompt`` with inspect's cache off (``cache=False``), so an eval-level
       ``GenerateConfig(cache=True)`` can't replay a reply. The first ask otherwise behaves
       like any judge call, AI Gateway cache included.
    2. Parse: ``parse`` returns the verdict, or ``None`` when the reply is unparseable. A
       blank reply never reaches ``parse``: the provider refuses it as
       :class:`JudgeReplyBlank`, which counts here as unparseable too. Only that error is
       caught; any other failed call propagates on the first ask, never redrawn.
    3. Redraw: on ``None``, ask again inside :func:`fresh_judge_draw`, which makes the
       gateway skip its exact-request cache for that call. Gotcha: the redraw is the SAME
       bytes as the first ask, so without the opt-out the cache would hand back the same
       broken text and every redraw would fail identically. Limit: leaving the cache only
       buys a fresh SAMPLE. A judge pinned at ``temperature=0`` decodes near-greedily, so
       the same bytes can bring the same bad reply back, and the redraw may be a wasted
       call; redrawing pays off when the judge samples.
    4. Give up: after ``MAX_JUDGE_REDRAWS`` redraws, raise :class:`JudgeReplyUnparseable`
       naming ``item`` and quoting the last reply's head. The scorer adapter turns it into
       the Case's ``judge_reply_invalid``; it never becomes "not met".

    Worked example (``MAX_JUDGE_REDRAWS = 2``, so at most 3 draws): replies
    ``["Let me think...", "MET"]`` → draw 1 unparseable, draw 2 parses → returns
    ``JudgedItem(verdict=True, redraws=1)``. Replies ``["...", "...", "..."]`` → three
    draws, no verdict → raises, and no fourth call is made.

    Args:
        judge: the inspect model to ask; on the plugin lane, the gateway judge provider.
        prompt: the item's grader prompt, a string or chat messages, the same every draw.
        parse: reply text → verdict; ``None`` means "no verdict in this reply". It must not
            raise for a merely malformed reply, or the item fails without a redraw.
        item: names the item in the error (e.g. ``"case 7 rubric r2"``).

    Returns:
        The parsed verdict and the number of redraws it took.

    Raises:
        JudgeReplyUnparseable: no parseable reply after ``MAX_JUDGE_REDRAWS`` redraws.
    """

    reply: str = ""
    for redraws in range(1 + MAX_JUDGE_REDRAWS):
        # Stage 1 / 3 — ask; every draw after the first leaves the gateway cache.
        try:
            if redraws:
                with fresh_judge_draw():
                    output: ModelOutput = await judge.generate(prompt, cache=False)
            else:
                output = await judge.generate(prompt, cache=False)
        except JudgeReplyBlank:
            # Stage 2 — a blank reply has no verdict: unparseable, so it costs a redraw.
            reply = ""
            continue
        reply = output.completion
        # Stage 2 — parse; a verdict ends the loop.
        verdict: Verdict | None = parse(reply)
        if verdict is not None:
            return JudgedItem(verdict=verdict, redraws=redraws)
    # Stage 4 — the budget is spent: fail by name, never as "not met".
    raise JudgeReplyUnparseable(
        f"the judge gave no parseable reply for {item} after {MAX_JUDGE_REDRAWS} redraws; "
        f"last reply: {reply[:_REPLY_HEAD_CHARS]!r}"
    )


__all__ = ["MAX_JUDGE_REDRAWS", "JudgeReplyUnparseable", "JudgedItem", "judge_until_parsed"]
