"""The MuSiQue prompt bytes ARE the Benchmark — pinned, because nothing else protects them.

WHY this file exists: MuSiQue is judge-free, so the prompt is the only thing between a model and
its score, and the same bytes feed the Benchmark Revision (spec: "byte-frozen; part of the
Benchmark Revision"). A reworded instruction would change every score while every other gate
stayed green. The frame is pinned as a hand-written literal; the real dev Case is pinned by the
sha256 of its full rendering, computed from the spec's template independently of `prompts.py`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.musique.answering import ExtractedReply, extract_reply
from screamingface_engine.benchmarks.musique.prompts import Paragraph, render_case_input

_FIXTURE: Path = Path(__file__).parents[1] / "fixtures/musique/dev_two_rows.jsonl"

#: Hand-written from the spec's "The prompt" block. Do NOT re-wrap or "tidy" any line.
_FRAME_LITERAL: str = (
    "Answer the question using the numbered paragraphs below.\n"
    "\n"
    "[0] First title\n"
    "First text.\n"
    "\n"
    "[1] Second title\n"
    "Second text.\n"
    "\n"
    "Question: Who wrote it?\n"
    "\n"
    "Think it through if that helps, then end your reply with these two lines, in this order:\n"
    "Supporting paragraphs: <the numbers of the paragraphs you used, comma-separated>\n"
    "Answer: <the answer, in as few words as possible>"
)

#: sha256 of the first fixture Case (`2hop__460946_294723`, 9,261 characters) rendered by the
#: spec's template, computed with a standalone script before `prompts.py` existed.
_FIRST_CASE_SHA256 = "f8e58a5f32e29e523fed54802b4a3ef87653aa7727d310918b34ff9a74358aed"
_FIRST_CASE_CHARS = 9261


def _first_fixture_row() -> dict[str, Any]:
    """The real dev Case `2hop__460946_294723`, as the dataset publishes it."""

    first_line: str = _FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    return json.loads(first_line)


def _paragraphs(row: dict[str, Any]) -> list[Paragraph]:
    """The row's paragraphs in the dataset's order, as the prompt receives them."""

    return [
        Paragraph(idx=p["idx"], title=p["title"], text=p["paragraph_text"])
        for p in row["paragraphs"]
    ]


def test_the_frame_is_byte_identical_to_the_spec() -> None:
    rendered: str = render_case_input(
        "Who wrote it?",
        [Paragraph(0, "First title", "First text."), Paragraph(1, "Second title", "Second text.")],
    )

    assert rendered == _FRAME_LITERAL


def test_the_first_fixture_case_renders_to_its_pinned_bytes() -> None:
    """INVARIANT: a real Case's full input — all 20 paragraphs — is byte-frozen."""

    row: dict[str, Any] = _first_fixture_row()

    rendered: str = render_case_input(row["question"], _paragraphs(row))

    assert len(rendered) == _FIRST_CASE_CHARS
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == _FIRST_CASE_SHA256
    assert rendered.startswith(
        "Answer the question using the numbered paragraphs below.\n\n[0] Grant's First Stand\n"
        "Grant's First Stand is the debut album"
    )
    assert "\n\nQuestion: Who is the spouse of the Green performer?\n\n" in rendered


def test_paragraphs_carry_the_datasets_own_numbers_in_the_datasets_order() -> None:
    """WHY (spec D4): support F1 compares the numbers the model cites with the gold
    `is_supporting` idx, so the prompt must show the dataset's idx, never a renumbering."""

    rendered: str = render_case_input(
        "q", [Paragraph(7, "Seventh", "x"), Paragraph(3, "Third", "y")]
    )

    assert rendered.index("[7] Seventh\nx") < rendered.index("[3] Third\ny")
    assert "[0]" not in rendered


def test_braces_in_dataset_text_are_rendered_literally() -> None:
    """Dataset text is data, not a template: a `{` in a question or paragraph must not be read
    as a format field, or a Case with braces would crash Case Preparation."""

    rendered: str = render_case_input("What is {x}?", [Paragraph(0, "T {0}", "Set {a, b}.")])

    assert "Question: What is {x}?" in rendered
    assert "[0] T {0}\nSet {a, b}." in rendered


def test_the_lines_the_prompt_asks_for_are_the_lines_the_parser_reads() -> None:
    """INVARIANT: the prompt's two closing lines, filled in, parse as two committed lines. If the
    prompt asked for a label the parser does not look for, every reply would be flagged missing
    and scored as a whole sentence."""

    closing: list[str] = _FRAME_LITERAL.splitlines()[-2:]
    filled: str = "\n".join(
        line.split(":", 1)[0] + ": " + value for line, value in zip(closing, ["10, 5", "X"])
    )

    reply: ExtractedReply = extract_reply(filled)

    assert reply == ExtractedReply(
        answer="X", answer_line=True, support=frozenset({5, 10}), support_line=True
    )
