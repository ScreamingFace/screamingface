"""The narrow steps in the Combine section and the run summary (E4b surface unit 6, DS-2).

FEATURE (rebuild-display §4): the Combine section shows one chip per narrow step
(``filter · kept 2 of 4``, ``rank top 2 · max``), the status cell of a member that a narrow step
left out says at which step and why (``left out at step 1: not selected``), and the run summary
counts, per narrow step, the members that step left out.
STORY: as a researcher, I see which members a Filter or a Rank left out before the vote.
INVARIANT defended: an evidence with no ``narrow`` key renders as before (no narrow chip, no
narrow line); the expected texts are hand-computed from ``narrow_evidence_cases.json``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui import combine_view
from screamingface.combine_evidence import CombineEvidence

_NO_LINK: dict[str, str | None] = {"judge_operation_id": None, "judge_model": None}


def _case(name: str) -> CombineEvidence:
    cases: dict[str, Any] = json.loads(
        (COMBINE_CONTRACT / "narrow_evidence_cases.json").read_text(encoding="utf-8")
    )
    evidence = decode_combine_evidence(cases[name], "combine")
    assert evidence is not None
    return evidence


def _section(name: str) -> str:
    return combine_view._section("op_synthesis_1", _case(name), _NO_LINK, {})


def _summary(*names: str) -> str:
    step = combine_view._StepSummary(_case(names[0]).reducer)
    for name in names:
        step.add(_case(name))
    return combine_view._summary_html("op_synthesis_1", step, {})


def _status_cells(html: str) -> list[str]:
    # the second cell of each member row is its status
    rows = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("</tr>")
    return [row.split("<td>")[2].split("</td>")[0] for row in rows if "<td>" in row]


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "chips"),
    [
        ("filter_mean", ["filter · kept 2 of 4"]),
        ("rank_vote", ["rank top 2 · max"]),
        ("narrow_no_signal", ["filter · kept 4 of 5", "rank top 2 · max"]),
        ("narrow_cut_not_met", ["filter · kept 2 of 5", "rank top 3 · max"]),
        ("narrow_no_votes", ["filter · kept 0 of 5"]),
    ],
)
def test_ds2_one_chip_per_narrow_step(name: str, chips: list[str]) -> None:
    html = _section(name)

    for chip in chips:
        assert f"<span class='sf-chip'>{chip}</span>" in html
    assert html.count("<span class='sf-chip'>filter · ") + html.count(
        "<span class='sf-chip'>rank top "
    ) == len(chips)


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "cells"),
    [
        (
            "filter_mean",
            [
                "answered",
                "left out at step 1: not selected",
                "answered",
                "left out at step 1: no signal",
            ],
        ),
        (
            "narrow_no_signal",
            [
                "answered",
                "left out at step 1: no signal",
                "left out at step 2: no signal",
                "left out at step 2: not selected",
                "answered",
            ],
        ),
        (
            "narrow_cut_not_met",
            [
                "left out at step 2: not selected",
                "left out at step 2: not selected",
                "left out at step 1: not selected",
                "left out at step 1: not selected",
                "left out at step 1: not selected",
            ],
        ),
    ],
)
def test_ds2_a_left_out_member_says_at_which_step(name: str, cells: list[str]) -> None:
    assert _status_cells(_section(name)) == cells


@requires_engine_app
def test_ds2_the_run_summary_counts_the_left_out_members_per_step() -> None:
    # narrow_no_signal: step 1 reads 5 and leaves out 1, step 2 reads 4 and leaves out 2;
    # narrow_cut_not_met: step 1 reads 5 and leaves out 3, step 2 reads 2 and leaves out 2.
    html = _summary("narrow_no_signal", "narrow_cut_not_met")

    assert (
        "<div class='sf-chips'><span class='sf-chip'>narrow · step 1 · filter · left out 4 of 10"
        "</span><span class='sf-chip'>narrow · step 2 · rank · left out 4 of 6</span></div>"
    ) in html


@requires_engine_app
def test_ds2_an_evidence_with_no_narrow_key_has_no_narrow_text() -> None:
    cases: dict[str, Any] = json.loads(
        (COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8")
    )
    for raw in cases.values():
        evidence = decode_combine_evidence(raw, "combine")
        assert evidence is not None and evidence.narrow is None
        step = combine_view._StepSummary(evidence.reducer)
        step.add(evidence)
        html = combine_view._section("op_x", evidence, _NO_LINK, {}) + combine_view._summary_html(
            "op_x", step, {}
        )
        assert "left out at step" not in html
        assert "narrow · " not in html
