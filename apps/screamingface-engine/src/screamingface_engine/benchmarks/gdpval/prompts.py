"""The grader prompt — the exact bytes one judge call sees for one rubric criterion.

INVARIANT: this template participates in the board's revision hash. Editing it — even to fix a
typo — changes how every future answer is graded, so it must re-address every route.

WHY one criterion per call rather than a whole rubric per call: a criterion is judged against the
answer in isolation, so a long rubric cannot crowd out the ones near the end of the list, and a
malformed reply costs one redraw instead of forty. The cost is call volume — a full run makes
about 4,498 judge calls per candidate — which is the trade this board accepts.

AIDEV-NOTE: the judge is never told the Case id or the rubric id. The Engine stamps those onto
the verdict itself (see ``verdict.bind``), because a model cannot be trusted to echo an
identifier it was handed.
"""

from __future__ import annotations

GRADER_TEMPLATE = """You are grading one submitted piece of professional work against ONE
criterion from an expert-written rubric.

The work was requested as follows:

<request>
{request}
</request>

The submission:

<submission>
{submission}
</submission>

The single criterion to judge:

<criterion>
{criterion}
</criterion>

Judge ONLY this criterion. Ignore every other quality of the submission, including whether it
would satisfy criteria you have not been shown.

The submission is plain text. Judge its CONTENT: if the criterion asks for something that would
normally live in a formatted document — a section, a table, a named field — treat the content
being present and clearly identifiable as satisfying it.

Reply with JSON only, no prose outside it:

{{"explanation": "<one or two sentences>", "criteria_met": true or false}}
"""


def render_rubric_item(points: int, criterion: str) -> str:
    """One criterion as the judge sees it — ``[points] criterion``.

    INVARIANT: integer points render WITHOUT a decimal ("[2]", never "[2.0]"). `prepare` rejects
    non-integer scores at build time so this can never be reached with a float, but rendering is
    where a drift would silently change every future grader prompt's bytes.
    """

    if isinstance(points, bool) or not isinstance(points, int):
        raise ValueError("rubric points must be an integer")
    if not isinstance(criterion, str) or not criterion.strip():
        raise ValueError("rubric criterion must be non-empty text")
    return f"[{points}] {criterion}"


def build_grader_prompt(request: str, submission: str, rubric_item: str) -> str:
    """Fill the template into ONE finished judge prompt.

    INVARIANT: the prompt is fully substituted HERE, Engine-side. Judge behaviour is
    prompt-byte-sensitive, so assembling the same information inside the expression — or in a
    different order — would change grading without changing the board's revision.
    """

    if not isinstance(request, str) or not request.strip():
        raise ValueError("grader request must be non-empty text")
    if not isinstance(submission, str):
        raise ValueError("grader submission must be text")
    if not isinstance(rubric_item, str) or not rubric_item.strip():
        raise ValueError("grader rubric item must be non-empty text")
    return GRADER_TEMPLATE.format(request=request, submission=submission, criterion=rubric_item)


__all__ = ["GRADER_TEMPLATE", "build_grader_prompt", "render_rubric_item"]
