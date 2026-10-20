"""A reducer Fusion with quorum or optional members (OME-1289 E4a x OME-1557).

FEATURE: ``sf.Fusion(members, synthesizer=<reducer>, quorum=…)`` and optional members compile to
a broadcast panel (one JSON row per member that answered) that the combine call reads as
``panel``. url4 checks the quorum and the required members first, exactly as for a Model
synthesizer, so the reducer sees only the members that answered.
STORY: as a researcher, I write a vote over optional samples with a quorum, and the vote still
runs when some samples fail; the report shows each failed sample as ``missing``.
INVARIANT defended: a Fusion with no quorum and no optional member keeps its url4 bytes, and a
Model synthesizer keeps main's text panel; only a reducer reads the broadcast panel.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from _answer_fixtures import bound, evidence_wires, fixture_graph
from _nodes import fusion_node
from _reducer_fixtures import FixtureVote, evidence_wire, fixture_operators
from url4 import expr, render, src, text

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.case_result import CaseOperation

_COMBINE_CALL = re.compile(
    r"synthesis_1:0\.0:/ensemble/combine/v1\?binding=synthesis_1&q=\((\{.*?\})\)!'"
)
_MEMBERS = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=fixture_operators()).url4


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def _combine_context(url4: str) -> str:
    """The context of the combine call ``synthesis_1``, as the url4 text holds it."""

    match = _COMBINE_CALL.search(url4)
    assert match is not None
    return match.group(1)


# --- QR-1 and QR-2: what compiles --------------------------------------------------------------


def test_a_quorum_reducer_reads_a_broadcast_panel() -> None:
    url4 = _url4(fusion_node(_MEMBERS, FixtureVote(), quorum=2))

    assert "!*'';quorum=2" in url4
    assert ";optional" in url4
    assert _combine_context(url4) == "{input: '$input', panel: '$panel_1'}"


def test_a_model_synthesizer_keeps_the_text_panel() -> None:
    url4 = _url4(sx.Fanout(_MEMBERS, quorum=2) >> sx.Synthesize("provider/s"))

    assert "!'';quorum=2" in url4
    assert "!*" not in url4
    assert "outputs: '$panel_1'" in url4


def test_a_reducer_with_every_member_required_has_no_panel() -> None:
    url4 = _url4(fusion_node(["provider/a", "provider/b", "provider/c"], FixtureVote()))

    assert "panel_" not in url4
    assert _combine_context(url4).startswith("{input: '$input', outputs: {member_1: '$model_1'")


def test_an_all_optional_fusion_without_a_quorum_still_needs_every_member() -> None:
    members = [sf.Model("provider/a", optional=True), sf.Model("provider/b", optional=True)]

    url4 = _url4(fusion_node(members, FixtureVote()))

    assert "!*'';quorum=2" in url4


# --- QR-4: replay and recovery -----------------------------------------------------------------


def test_a_quorum_reducer_round_trips_through_url4() -> None:
    fusion = fusion_node(_MEMBERS, FixtureVote(), quorum=2)
    compiled = compile_candidate(fusion, operators=fixture_operators())

    assert _url4(_recovered(compiled.url4)) == compiled.url4
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations


# --- QR-10: the report shows a missing member -------------------------------------------------


def test_the_evidence_decodes_a_missing_member() -> None:
    wire = evidence_wire(3)
    wire["members"][2].update(raw=None, value=None, status="fail", reason="missing", weight=None)
    wire["members"][2]["score"] = None
    wire["tally"] = [{"value": "12", "score": 2.0, "holders": ["member_1", "member_2"]}]
    wire["dropped"] = 1

    evidence = decode_combine_evidence(wire, "op_synthesis_1 evidence")

    assert evidence is not None

    missing = evidence.members[2]
    assert (missing.member_id, missing.status, missing.reason) == ("member_3", "fail", "missing")


def test_a_missing_member_has_no_text_in_the_answers() -> None:
    wire = copy.deepcopy(evidence_wires()["vote_one_failed"])
    assert wire["members"][1]["status"] == "fail"
    wire["members"][1]["reason"] = "missing"
    evidence = decode_combine_evidence(wire, "op_synthesis_1 evidence")
    assert evidence is not None
    case = sf.CaseResult(
        case_id=1,
        input="Question 1",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=[
            CaseOperation("op_model_1", "text 1", "stop"),
            CaseOperation("op_model_2", None, None),
            CaseOperation("op_model_3", "text 3", "stop"),
            CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence),
        ],
    )

    answers = bound(case, fixture_graph(3)).answers()

    missing = answers[1]
    assert (missing.member_id, missing.status, missing.reason, missing.text) == (
        "member_2",
        "fail",
        "missing",
        None,
    )
    assert [a.text for a in answers[:3]] == ["text 1", None, "text 3"]
