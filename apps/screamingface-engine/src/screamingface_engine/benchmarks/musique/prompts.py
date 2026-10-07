"""The pinned MuSiQue-Ans Case input — one user message, byte-frozen (spec D3, D4, D5).

INVARIANT: these bytes feed the benchmark's revision hash, so an edit here is a new benchmark
identity, not a tweak. `tests/unit/test_musique_prompts.py` pins the frame as a hand-written
literal and a real Case by the sha256 of its full rendering.

WHY there is no official prompt to copy: the paper's models were fine-tuned, so the wording is
ours (spec, "The prompt"). Three choices in it carry the score:

- paragraphs show the dataset's own `idx` (`[5] Title`), because support F1 compares the
  numbers the model cites with the gold `is_supporting` idx;
- the reply ENDS with `Supporting paragraphs:` then `Answer:`, so a model may reason first and
  still commit a clean span — a full-sentence answer loses F1 for wording, not knowledge;
- there is no system message: that belongs to the Candidate's Recipe, not to the Case.

The rendered input has no trailing newline; the spec's prompt block ends at the `Answer:` line.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: The opening line, the slot for every paragraph, the question, then the two closing lines the
#: parser reads. Filled with `str.format`, which treats braces INSIDE the substituted values as
#: plain text, so a `{` in a question or paragraph renders literally.
CASE_TEMPLATE = (
    "Answer the question using the numbered paragraphs below.\n"
    "\n"
    "{paragraphs}\n"
    "\n"
    "Question: {question}\n"
    "\n"
    "Think it through if that helps, then end your reply with these two lines, in this order:\n"
    "Supporting paragraphs: <the numbers of the paragraphs you used, comma-separated>\n"
    "Answer: <the answer, in as few words as possible>"
)

#: One paragraph: its dataset number and title on one line, its text on the next.
PARAGRAPH_TEMPLATE = "[{idx}] {title}\n{text}"

#: Paragraphs are separated by one blank line, in the dataset's order.
PARAGRAPH_SEPARATOR = "\n\n"


@dataclass(frozen=True, slots=True)
class Paragraph:
    """One numbered paragraph as the Candidate sees it — the dataset's `idx`, title and text."""

    idx: int
    title: str
    text: str


def render_case_input(question: str, paragraphs: Sequence[Paragraph]) -> str:
    """The exact Candidate-facing text for one Case — every paragraph, then the question."""

    rendered: str = PARAGRAPH_SEPARATOR.join(
        PARAGRAPH_TEMPLATE.format(idx=p.idx, title=p.title, text=p.text) for p in paragraphs
    )
    return CASE_TEMPLATE.format(paragraphs=rendered, question=question)


__all__ = [
    "CASE_TEMPLATE",
    "PARAGRAPH_SEPARATOR",
    "PARAGRAPH_TEMPLATE",
    "Paragraph",
    "render_case_input",
]
