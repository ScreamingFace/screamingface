"""inspect's own multiple-choice scorer (35 rows): the reply must end `ANSWER: B`."""

from __future__ import annotations

from collections.abc import Mapping

from screamingface_engine_inspect.answer_formats._format import AnswerFormat

#: WHY these replies: inspect_ai v0.3.263's parser takes only letters, digits, spaces and commas
#: right after `ANSWER:` (`solver/_multiple_choice.py:98-110`), so a mark before the letter was
#: no answer; since OME-1907 the scorer adapter peels such a wrapper from a copy of the reply
#: when inspect reads nothing (`named_deviations/wrapped_letter`), so `ANSWER: $B` grades 1.
#: Words after the letter, or no `ANSWER:` label, are still no answer, as inspect reads them.
CHOICE: Mapping[str, AnswerFormat] = {
    "inspect_ai.scorer:choice": AnswerFormat(
        sentence=(
            "Answer format: end the reply with a line like 'ANSWER: B', the letter of one "
            "option. A period after it still counts, as in 'ANSWER: B.', and so does a wrapper "
            "around the letter, as in 'ANSWER: $B$', 'ANSWER: (B)', 'ANSWER: **B**' or "
            "'ANSWER: \\boxed{B}'. Words after the letter, as in 'ANSWER: B because it is red', "
            "or a reply with no 'ANSWER:' line, as in 'The answer is B', are read as no answer "
            "and score 0, even when the letter is right."
        ),
        case_input="Which seat is free?\n\nA) 1\nB) 2",
        material={"target": "B", "choices": ["1", "2"]},
        accepted=(
            "ANSWER: B",
            "ANSWER: B.",
            "ANSWER: $B$",
            "ANSWER: (B)",
            "ANSWER: **B**",
            "ANSWER: \\boxed{B}",
        ),
        rejected=("ANSWER: B because it is red", "The answer is B"),
    ),
}
