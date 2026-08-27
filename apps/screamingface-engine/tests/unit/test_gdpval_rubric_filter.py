"""Container-vs-content: which rubric criteria a plain-text answer may fairly be judged on.

STORY: as a reader of a GDPval score, I need the number to reflect the CONTENT of the answer,
not the fact that we submitted plain text where a Word document was expected.

INVARIANT under test: the filter removes criteria that judge the DELIVERED FILE and keeps every
criterion that judges what the answer SAYS. Over-removal is the dangerous direction — it shrinks
the denominator and inflates every candidate's score — so the content cases below are the
load-bearing half of this file.

AIDEV-NOTE: every fixture is a REAL criterion copied from the published rubrics of the 102
selected tasks (2026-08-24). Invented fixtures are how the first version of this filter passed
its tests while deleting seven content criteria in production, including a -10 penalty.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.gdpval.rubric_filter import (
    FILTER_REVISION,
    is_format_criterion,
    strip_format_criteria,
)

# Criteria that judge the delivered FILE — unearnable by a text answer, so they are removed.
_CONTAINER = (
    "Exactly one checklist file is provided in PDF format.",
    "Deliverable is a Microsoft Word file.",
    "A single PDF file is delivered.",
    "Submitted PDF filename is ‘T.H’ (case-insensitive), with a .pdf extension.",
    "Submission is provided as a Microsoft Word (.docx) document",
    "Provides two separate .docx files: one escalation email and one vendor assessment report "
    "(not combined).",
    # v2 — delivery phrasings the v1 verb list waved through (found in the first live runs):
    "Creates the document as a PDF file.",
    "Presents completed checklist as a PDF file.",
    "Submits exactly one PDF file containing the legal memorandum",
    "Submits an editable .docx file that opens without error in Microsoft Word.",
    "LOI is a Word document",
    "Contains a deliverable flowchart document is a PDF file.",
    "Contains an incident details document in the form of a powerpoint (.ppt or .pptx) or PDF file",
)

# Criteria that judge what the answer SAYS, while naming a container or a reference file.
# A text answer can satisfy every one of these, so removing any of them would inflate scores.
_CONTENT = (
    "The Word document includes a field for Employee Email.",
    "The Word document contains a clearly labeled 'Process' section.",
    "In Section 1, vendor names correspond to the vendors listed in VENDOR SCHEDULES .pdf "
    "(case-insensitive; minor punctuation variants acceptable).",
)

# WHY these three specifically: the naive first filter deleted them because a REFERENCE filename
# happens to end in .docx. They are regression anchors — if any starts being filtered again, the
# denominator is shrinking and scores are silently inflating.
_QUOTED_REFERENCE_TRAPS = (
    "Narration content is substantively consistent with page 1 of the reference "
    "('Nature Doc Key Info and VO.docx'), covering all specified narrator lines/topics verbatim "
    "or via faithful paraphrase",
    "The reference sheet 'WordDoc_ResearchFormatReferenceSheet.docx.docx' is used for "
    "formatting suggestions.",
    'Structures the deliverable in a way that is inconsistent with "NEW CMA template.docx"',
)

# Known, accepted misses — documented rather than chased. Worth ~6 of 7,183 positive points
# (0.08%). Each reads as content by phrasing ("contains", no delivery verb) while actually
# checking the file. Chasing them costs more false-positive risk than the points are worth.
_ACCEPTED_MISSES = (
    "The .docx opens without error.",
    "Output contains a single Excel file",
    "The Word document is no longer than 6 pages",
)


def test_container_criteria_are_removed() -> None:
    for criterion in _CONTAINER:
        assert is_format_criterion(criterion), criterion


def test_content_criteria_are_kept_even_when_they_name_a_container() -> None:
    # INVARIANT: over-removal inflates every candidate's score. This is the half that matters.
    for criterion in _CONTENT:
        assert not is_format_criterion(criterion), criterion


def test_a_quoted_reference_filename_is_not_a_format_demand() -> None:
    for criterion in _QUOTED_REFERENCE_TRAPS:
        assert not is_format_criterion(criterion), criterion


def test_accepted_misses_are_pinned_so_the_residual_stays_visible() -> None:
    # WHY assert the CURRENT behaviour: if a later change starts catching these, that is an
    # improvement worth noticing deliberately rather than a silent shift in the answer key.
    for criterion in _ACCEPTED_MISSES:
        assert not is_format_criterion(criterion), criterion


def test_detection_is_case_insensitive() -> None:
    assert is_format_criterion("SUBMISSION IS PROVIDED AS A MICROSOFT WORD (.DOCX) DOCUMENT")


def test_strip_removes_only_container_criteria_and_preserves_order() -> None:
    items = [
        {"criterion": _CONTENT[0], "score": 1},
        {"criterion": _CONTAINER[0], "score": 2},
        {"criterion": _CONTENT[1], "score": 2},
    ]
    assert [i["criterion"] for i in strip_format_criteria(items)] == [_CONTENT[0], _CONTENT[1]]


def test_strip_on_an_all_content_rubric_is_a_no_op() -> None:
    items = [{"criterion": c, "score": 1} for c in _CONTENT]
    assert strip_format_criteria(items) == items


def test_filter_revision_is_a_nonempty_identifier() -> None:
    # INVARIANT: hashed into the board revision — an unnamed filter could change scores without
    # re-addressing the routes.
    assert FILTER_REVISION.strip()
