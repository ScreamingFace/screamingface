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

__all__ = ["GRADER_TEMPLATE"]
