"""The Combine views of the report (E4b part 4): the Case pane section and the run summary.

RED stub (E4b part 4 unit 2, commit A). The GREEN commit fills each name. No render path calls
these functions yet, so they may raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screamingface.combine_evidence import CombineAnswerRow

STYLE = ""


def number_html(value: float | None, reason: str) -> str:
    raise NotImplementedError


def dash_html(reason: str) -> str:
    raise NotImplementedError


def text_html(value: str | None, reason: str) -> str:
    raise NotImplementedError


def missing_reason(row: CombineAnswerRow, label: str) -> str:
    raise NotImplementedError
