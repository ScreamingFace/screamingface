"""The LABBench2 authors' exact-match judge prompt and file-mode question text, vendored.

Copied byte for byte from EdisonScientific/labbench2 at commit ``0cabab27``, the authors'
evaluation harness for LABBench2 (Laurent et al., 2026). Licensed CC BY-SA 4.0 by its
authors; this file is a verbatim excerpt and stays under that licence (attribution and
share-alike), as the LABBench2 dataset itself does.

Sources, at the pinned commit:

- ``STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH``:
  https://github.com/EdisonScientific/labbench2/blob/0cabab27f6a23a5bc060a4699205709f1be7e93f/evals/prompts.py#L34-L67
  The judge prompt the authors' ``HybridEvaluator`` uses for figqa2, tableqa2 and their
  ``-img`` variants, including their 2026-10-07 rule for a ground truth that is not a number.
- ``file_mode_question``: the ``mode == "file"`` branch of ``evals/loader.py`` (L86-L97)
  and its prompt suffix (L108-L109),
  https://github.com/EdisonScientific/labbench2/blob/0cabab27f6a23a5bc060a4699205709f1be7e93f/evals/loader.py#L86-L109
  written as a function over file names; the authors build the same string inline.

Licence: https://github.com/EdisonScientific/labbench2/blob/0cabab27f6a23a5bc060a4699205709f1be7e93f/LICENSE

AIDEV-NOTE: never edit the prompt text here. A change in the authors' harness is a new pin:
copy the new text, move the commit in this header, and expect the Benchmark's revision to
move (the Task's source digest covers this file).
"""

from __future__ import annotations

from collections.abc import Sequence

STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH = """\
You are a helpful assistant that evaluates the correctness of an answer.

You are given a question, a ground truth answer, and a submitted answer.
The ground truth answer and the submitted answer may be written in different formats
(e.g., standard notation, commas, spaces, or scientific notation).

Your task:
- Interpret both answers as numbers (ignore formatting differences) unless the
  question explicitly specifies a required format (e.g., number of decimal
  places, scientific notation, units, etc.).
- Accept scientific notation if it represents the same numeric value.
- Consider the answer correct if the absolute or relative difference is less
  than 1e-6, and formatting matches any explicit requirements in the question.
- If the numbers are not equivalent within this tolerance, mark as "incorrect".
- If the ground truth answer is not a number, mark as "correct" only if the submitted
  answer states the same answer, otherwise mark as "incorrect".
- If you cannot determine numeric equivalence, mark as "unsure".

Your output should include the following fields:
- rationale: A short explanation of your evaluation.
- result: MUST be one of the following words: "correct", "incorrect", or "unsure".

## QUESTION ##
{question}

## GROUND TRUTH ANSWER ##
{correct_answer}

## SUBMITTED ANSWER ##
{answer}

## EVALUATION ##
"""


def file_mode_question(question: str, file_names: Sequence[str], prompt_suffix: str = "") -> str:
    """The question text the authors' loader hands the model in file mode.

    The question, then the attached files' base names as a list, then the instruction to cite
    them by base name, then the row's prompt suffix after a blank line when it has one.
    Worked example, one figure and no suffix:
    ``"Which contrast ...?\\n\\nAttached files:\\n- figure.png\\n\\nUse only the exact base
    filenames above. ..."``.
    """

    question_text: str = question
    file_list: str = "\n".join(f"- {name}" for name in file_names)
    question_text += (
        f"\n\nAttached files:\n{file_list}\n\n"
        "Use only the exact base filenames above. Copy them exactly, including case and extension. "
        "Do not rename them or use full paths."
    )
    if prompt_suffix:
        question_text += "\n\n" + prompt_suffix
    return question_text
