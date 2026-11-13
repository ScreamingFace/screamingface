"""inspect's own multiple-choice scorer (35 rows): the reply must end `ANSWER: B`."""

from __future__ import annotations

from collections.abc import Mapping

from screamingface_engine_inspect.answer_formats._format import AnswerFormat

#: WHY these rejected replies: inspect_ai v0.3.263's parser takes only letters, digits, spaces
#: and commas right after `ANSWER:` (`solver/_multiple_choice.py:98-110`), so any mark before
#: the letter is no answer. A mark after it is tolerated by the fallback pattern, which allows
#: any non-word character after the letters: `ANSWER: B.` grades 1, and the sentence says only
#: that much of the tolerant side. `ANSWER: $B` is the shape that cost a submitter a run
#: (OME-1886).
CHOICE: Mapping[str, AnswerFormat] = {
    "inspect_ai.scorer:choice": AnswerFormat(
        sentence=(
            "Answer format: end the reply with a line like 'ANSWER: B', the bare letter of one "
            "option; a period after it, as in 'ANSWER: B.', still counts. Any mark between "
            "'ANSWER:' and the letter, such as 'ANSWER: $B', 'ANSWER: (B)', 'ANSWER: **B**' or "
            "'ANSWER: \\boxed{B}', is read as no answer and scores 0, even when the letter is "
            "right."
        ),
        case_input="Which seat is free?\n\nA) 1\nB) 2",
        material={"target": "B", "choices": ["1", "2"]},
        accepted=("ANSWER: B", "ANSWER: B."),
        rejected=("ANSWER: $B", "ANSWER: (B)", "ANSWER: **B**", "ANSWER: \\boxed{B}"),
    ),
}
