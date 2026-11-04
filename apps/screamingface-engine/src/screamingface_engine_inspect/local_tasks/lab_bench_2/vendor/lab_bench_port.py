"""The inspect port's judge-verdict reader for LABBench2, vendored.

Copied verbatim from Generality-Labs/lab-bench at commit ``081864a``, the inspect port that
inspect_evals' register entry for LABBench2 points to. MIT licence, Copyright (c) 2025 its
authors: https://github.com/Generality-Labs/lab-bench/blob/081864af494b180ecf6aae3f7333e384c0d227af/LICENSE

Sources, at the pinned commit
(https://github.com/Generality-Labs/lab-bench/blob/081864af494b180ecf6aae3f7333e384c0d227af/src/lab_bench_2/scorers.py):

- the three verdict words and ``_GRADE_PATTERN``, L39-L47;
- ``parse_judge_verdict``, L347-L356.

WHY this reader: the port asks its judge for a JSON response schema and falls back to this
regex when the reply does not validate. Our judge provider does not send a response schema
(a Named Deviation), so every reply takes the port's fallback path. The authors' prompt asks
for a ``result:`` field in every reply, which is what this pattern reads.

AIDEV-NOTE: never edit the pattern here; a new pin copies the new code and moves the commit.
"""

from __future__ import annotations

import re

JUDGE_VERDICT_CORRECT = "correct"
JUDGE_VERDICT_INCORRECT = "incorrect"
JUDGE_VERDICT_UNSURE = "unsure"
# Excluding ``=`` from the separator stops the pattern from matching code-like
# grader output such as ``result = "correct"`` (an assignment, not a verdict).
_GRADE_PATTERN = re.compile(
    r"\bresult\b[^A-Za-z=]*(correct|incorrect|unsure)\b",
    re.IGNORECASE,
)


def parse_judge_verdict(text: str) -> str | None:
    """Return the judge's verdict, or None if no verdict line is present.

    When multiple verdict lines appear (e.g. the rubric words echoed earlier in
    the reasoning), the last match is taken as the final verdict.
    """
    matches = _GRADE_PATTERN.findall(text or "")
    if not matches:
        return None
    return str(matches[-1]).lower()
