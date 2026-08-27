"""Separate criteria that judge the DELIVERED FILE from those that judge what the answer SAYS.

STORY: as a reader of a GDPval score, I need the number to reflect the CONTENT of the answer,
not the fact that we submitted plain text where a Word document was expected.

A GDPval rubric is a checklist; the judge ticks each line against the candidate's answer and the
Case score is points earned over points available. Most lines judge content and transfer to a
text answer unchanged. A minority judge the artifact itself — "provided as a Microsoft Word
(.docx) document", "A single PDF file is delivered". This board never produces a file, so every
candidate fails those identically. They are stripped in ``prepare`` and never reach the baked
assets.

INVARIANT: filtering happens at BUILD time, so no scoring path can include a container criterion
by accident. ``FILTER_REVISION`` is hashed into the board revision — changing the rules below
changes which criteria are scored, and must therefore re-address every route.

Measured over the 4,553 criteria of the 102 selected tasks (2026-08-27, rules v2): 106 removed,
worth 224 of 7,183 positive points (3.1%). A hand audit of the removals found no content
criterion among them. Known misses remain — page counts, Track-Changes mechanics — all phrased
as content ("appears", "includes"); rules aggressive enough to catch them risk deleting real
content criteria, which inflates scores. See ``test_gdpval_rubric_filter.py``.

AIDEV-NOTE: over-removal is the DANGEROUS direction. Deleting a content criterion shrinks the
denominator and inflates every candidate's score; missing a container criterion penalises every
candidate equally and stays visible in the score. The first version of this module was a bare
keyword match and deleted seven content criteria — including a -10 penalty — because a
REFERENCE filename ended in ``.docx``. Hence rule 1 below. When in doubt, KEEP the criterion.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# WHY: hashed into the board revision. Bump when any rule below changes.
FILTER_REVISION = "container-vs-content-v2"

# Rule 1 — a filename inside quotes is a REFERENCE the answer must be consistent with, never a
# demand about the deliverable's own format. Strip quoted spans before looking for format words.
# WHY: "…consistent with page 1 of the reference ('Nature Doc Key Info and VO.docx')" is a
# content criterion that a bare ``.docx`` match destroys.
_QUOTED = re.compile(
    r"['\"‘’“”][^'\"‘’“”]{0,140}"
    r"['\"‘’“”]"
)

# Rule 2 — the criterion must name a file format at all. Necessary, never sufficient.
_FORMAT = re.compile(
    r"\.(docx?|xlsx?m?|pptx?|pdf|csv|md|txt|rtf|pages|dotx|dotm|png|jpe?g)\b"
    r"|\b(word|excel|powerpoint)\s+(document|file|workbook|deck|format)"
    r"|\bpdf\s+(file|format|document)\b"
    r"|\bfile\s+format\b|\bbasename\b|\bfilename\b"
)

# Rule 3 — the discriminator. A container criterion asserts the ACT OF DELIVERY: what was
# handed over, how many, under what name. A content criterion asserts what is INSIDE.
# "The Word document CONTAINS a 'Process' section" is content; a text answer satisfies it.
_DELIVERY = re.compile(
    r"\b(provided|provides|delivered|delivers|submitted|submission|submits?|deliverable\s+is|"
    r"attached|uploaded|is\s+delivered|are\s+provided)\b"
    # v2 — three delivery phrasings the verb list missed (each escaped v1 in the live rubrics):
    # "Creates/Presents the document AS A PDF file" — delivery said through an as-construction;
    r"|\b(creates?|presents?|saves?|exports?)\b[^.]{0,60}\bas\s+an?\s+"
    # "The LOI IS A Word document" — the deliverable's identity asserted with no verb at all;
    r"|\bis\s+an?\s+(single\s+)?(word|pdf|excel|powerpoint)\b"
    # "…IN THE FORM OF a powerpoint or PDF file" — format demanded as the vessel.
    r"|\bin\s+the\s+form\s+of\b"
)
_CONTENT = re.compile(
    r"\b(contains|includes|shows|lists|states|displays|identifies|describes|explains|"
    r"recommends|specifies|notes)\b"
)


def is_format_criterion(criterion: str) -> bool:
    """True when a criterion judges the delivered FILE rather than the answer's content."""

    text = _QUOTED.sub(" ", criterion).casefold()
    if not _FORMAT.search(text):
        return False
    # INVARIANT: content phrasing wins unless the criterion also asserts delivery. This is the
    # asymmetry that keeps over-removal rare.
    if _CONTENT.search(text) and not _DELIVERY.search(text):
        return False
    return bool(_DELIVERY.search(text))


def strip_format_criteria(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop container criteria, preserving the order of everything else.

    INVARIANT: order is preserved — rubric position is part of the baked answer key.
    """

    return [item for item in items if not is_format_criterion(str(item["criterion"]))]


def format_criteria_count(items: Sequence[Mapping[str, Any]]) -> int:
    """How many criteria ``strip_format_criteria`` would remove — for build-time reporting."""

    return len(items) - len(strip_format_criteria(items))


__all__ = [
    "FILTER_REVISION",
    "format_criteria_count",
    "is_format_criterion",
    "strip_format_criteria",
]
