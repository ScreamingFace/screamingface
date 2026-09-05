"""Answer-time letter extraction — the verbatim-official parser.

INVARIANT: this reads a TRIGGER COMPLETION. Turn 2 is the bare sentence "…the answer is", so the
model's commitment is the FIRST in-range letter it writes. First-match is correct here.

AIDEV-NOTE: this is NOT `grading.extract_letter`, and the two must never be merged. That one
reads arbitrary prose and takes the LAST match, because prose concludes at the end. Applying THIS
parser to a letter-last essay returns the first REJECTED option: the prior implementation did
exactly that and measured 35.5% where the true score was 70.2%. `test_medxpert_grading.py`
pins the divergence.
"""

from __future__ import annotations

import re

from screamingface_engine.benchmarks.medxpert.prompts import COT_TRIGGER_TEMPLATE

# Ported verbatim from the official `answer_cleansing()`. These are phrases a model echoes back
# from the trigger; "A through J" contains both A and J, so without this strip an echoed
# completion would parse as choice A on essentially every row.
_UNWANTED_PHRASES = ("I understand", "A through J", "A through E", "A through D")

_MAX_OPTIONS = 10


def format_trigger(options_count: int) -> str:
    """The turn-2 trigger for a row with ``options_count`` choices."""

    end = chr(ord("A") + _clamp(options_count) - 1)
    return COT_TRIGGER_TEMPLATE.format(start="A", end=end)


def extract_choice_letter(
    completion: str, options_count: int, trigger: str | None = None
) -> str | None:
    """The committed letter, or ``None`` when the model committed to nothing.

    Port of the official ``answer_cleansing()`` zero-shot branch: cut everything before the
    trigger if the model echoed it, strip the echo phrases, then take the FIRST letter inside
    this row's option range.

    INVARIANT: returns ``None`` rather than guessing. Callers turn that into an empty answer,
    which the grader scores wrong — the official empty-prediction verdict. A parser that guessed
    would rescue rows the reference kills and inflate every score.
    """

    text = (completion or "").strip()
    if not text:
        return None
    if trigger and trigger in text:
        text = text.split(trigger, 1)[1].strip()
    elif " answer is " in text:
        text = text.split(" answer is ", 1)[1].strip()
    for phrase in _UNWANTED_PHRASES:
        text = text.replace(phrase, "")

    letters = "|".join(chr(ord("A") + i) for i in range(_clamp(options_count)))
    found = re.findall(rf"\b({letters})\b", text)
    return found[0] if found else None


def _clamp(options_count: int) -> int:
    """Keep the option range inside A-J.

    WHY clamp instead of raise: `prepare` validates option shape at build time, so a bad count
    reaching here is an internal defect rather than bad data. Keeping this function total means a
    defect cannot take down a paid run mid-flight; the build is where rows are refused.
    """

    return max(1, min(int(options_count), _MAX_OPTIONS))


__all__ = ["extract_choice_letter", "format_trigger"]
