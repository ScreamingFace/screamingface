"""The SDK decodes the narrow evidence the real Engine writes (E4b map-reduce surface, unit 1).

FEATURE: an evidence of a combine call with narrow steps has a ``narrow`` record per step that ran
(``CombineNarrow``: select, signal, kept, cut, scores, ranks), and a member that a narrow step left
out has the reason ``not_selected`` (or ``no_signal``).
STORY: as a researcher, I read on the Case which narrow step left each member out, with the same
words as the Engine.
INVARIANT defended: the Engine's ``narrow_evidence_cases.json`` (pinned by
``ET/test_combine_narrow.py``) decodes strictly and writes back unchanged; an evidence with no
``narrow`` key decodes with ``narrow is None`` (old bytes); ``not_selected`` is an exclude reason
and nothing else. This test only READS the Engine file; it is skipped only when the Engine app
directory is absent (an installed run).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app
from test_frozen_record_fields import _fixture_case

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.answer import ANSWER_REASONS, EXCLUDE_REASONS
from screamingface.combine_evidence import (
    MAX_NARROW_STEPS,
    CombineAnswerRow,
    CombineCut,
    CombineEvidence,
    CombineNarrow,
)
from screamingface.errors import ExecutionError
from screamingface.report import CombineNarrow as ReportCombineNarrow

_CASES = COMBINE_CONTRACT / "narrow_evidence_cases.json"
_EXPECTED_NAMES = (
    "filter_mean",
    "rank_vote",
    "filter_rank_envelope",
    "narrow_no_votes",
    "narrow_cut_not_met",
    "narrow_no_signal",
    "judge_rank_weighted_vote",
    "judge_rank_after_filter",
    "judge_argmax_after_filter",
    "gate_after_narrow",
)


def _cases() -> dict[str, Any]:
    assert _CASES.is_file(), f"missing Engine contract fixture {_CASES}"
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _full(message: str) -> str:
    return f"^{re.escape(message)}$"


def _invalid(message: str) -> str:
    """The whole decode refusal of a value check: the label, then the record's own message."""
    return f"Engine evidence is invalid: {message}"


def _decode_refused(wire: dict[str, Any], message: str) -> None:
    with pytest.raises(ExecutionError, match=_full(message)):
        decode_combine_evidence(wire, "Engine evidence")


def _decoded(name: str) -> CombineEvidence:
    decoded = decode_combine_evidence(_cases()[name], f"Engine evidence {name}")
    assert isinstance(decoded, CombineEvidence)
    return decoded


# --- NR-13 ----------------------------------------------------------------------------------------


@requires_engine_app
def test_the_engine_narrow_fixture_holds_the_scenarios() -> None:
    assert tuple(_cases()) == _EXPECTED_NAMES


@requires_engine_app
@pytest.mark.parametrize("name", _EXPECTED_NAMES)
def test_sdk_decodes_the_narrow_contract_cases(name: str) -> None:
    wire = _cases()[name]

    decoded = decode_combine_evidence(wire, f"Engine evidence {name}")

    assert isinstance(decoded, CombineEvidence)
    assert decoded.narrow is not None
    assert decoded.to_dict() == wire


@requires_engine_app
def test_sdk_reads_the_rank_vote_record() -> None:
    narrow = _decoded("rank_vote").narrow

    assert narrow == (
        CombineNarrow(
            reduce="by_signal@1",
            select="top_k@1",
            signal="field:confidence",
            kept=("member_1", "member_2"),
            cut=CombineCut(2, "max"),
            scores={
                "member_1": 0.9,
                "member_2": 0.8,
                "member_3": 0.1,
                "member_4": 0.2,
                "member_5": 0.3,
            },
            ranks={"member_1": 1, "member_2": 2, "member_3": 5, "member_4": 4, "member_5": 3},
        ),
    )


@requires_engine_app
def test_sdk_reads_a_pattern_free_filter_record_with_no_cut_and_no_ranks() -> None:
    narrow = _decoded("filter_mean").narrow
    assert narrow is not None
    (record,) = narrow

    assert (record.reduce, record.select, record.signal, record.kept) == (
        "filter@1",
        "kept@1",
        "field:confidence",
        ("member_1", "member_3"),
    )
    assert record.cut is None
    assert record.ranks is None
    assert "cut" not in record.to_dict()
    assert "ranks" not in record.to_dict()


@requires_engine_app
def test_sdk_reads_the_left_out_members_with_their_reasons() -> None:
    members = _decoded("narrow_no_signal").members

    assert [(row.status, row.reason) for row in members] == [
        ("answered", None),
        ("excluded", "no_signal"),
        ("excluded", "no_signal"),
        ("excluded", "not_selected"),
        ("answered", None),
    ]


@requires_engine_app
def test_an_evidence_without_the_narrow_key_decodes_with_narrow_none() -> None:
    cases = json.loads((COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8"))

    for name, wire in cases.items():
        decoded = decode_combine_evidence(wire, f"Engine evidence {name}")
        assert decoded is not None
        assert decoded.narrow is None
        assert "narrow" not in decoded.to_dict()


@requires_engine_app
def test_not_selected_without_a_narrow_record_is_refused() -> None:
    wire = copy.deepcopy(_cases()["filter_mean"])
    del wire["narrow"]

    _decode_refused(
        wire,
        _invalid("Combine evidence not_selected goes with a narrow record, and only with it"),
    )


@requires_engine_app
def test_an_unknown_narrow_record_key_is_refused() -> None:
    wire = copy.deepcopy(_cases()["filter_mean"])
    wire["narrow"][0]["order"] = "max"

    _decode_refused(wire, "Engine evidence narrow[0] contains unsupported field 'order'")


@requires_engine_app
def test_a_later_kept_that_is_not_a_subset_is_refused() -> None:
    wire = copy.deepcopy(_cases()["narrow_no_signal"])
    wire["narrow"][1] = {"reduce": "filter@1", "select": "kept@1", "kept": ["member_1", "member_2"]}

    _decode_refused(
        wire, _invalid("Combine evidence kept of a narrow step is a subset of the step before")
    )


def test_combine_narrow_is_public_on_report() -> None:
    assert ReportCombineNarrow is CombineNarrow


def test_a_combine_narrow_record_checks_its_own_ranks() -> None:
    with pytest.raises(ValueError, match=_full("Combine narrow record has ranks only with a cut")):
        CombineNarrow(
            select="top_k@1", kept=("member_1",), scores={"member_1": 1.0}, ranks={"member_1": 1}
        )
    with pytest.raises(
        ValueError, match=_full("Combine narrow ranks are 1..n over the scored members")
    ):
        CombineNarrow(
            select="top_k@1",
            kept=("member_1",),
            cut=CombineCut(1, "max"),
            scores={"member_1": 1.0, "member_2": 0.5},
            ranks={"member_1": 1, "member_2": 3},
        )


# --- NR-14 ----------------------------------------------------------------------------------------


def test_not_selected_is_an_exclude_reason() -> None:
    assert "not_selected" in EXCLUDE_REASONS
    assert "not_selected" in ANSWER_REASONS
    assert EXCLUDE_REASONS == {"no_signal", "no_weight", "not_selected"}


def test_an_excluded_answer_may_be_not_selected() -> None:
    answer = sf.Answer(
        member_id="member_2",
        text="B",
        raw="b",
        value="b",
        status="excluded",
        reason="not_selected",
        signals={"field:confidence": 0.1},
    )

    assert answer.reason == "not_selected"
    assert sf.Answer.from_dict(answer.to_dict()) == answer


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("answered", "Answer has a reason exactly when it did not answer"),
        ("fail", "Answer has an exclude reason exactly when it was excluded"),
        ("abstain", "an abstain Answer has no member and an abstain reason"),
    ],
)
def test_not_selected_goes_with_excluded_only(status: str, message: str) -> None:
    with pytest.raises(ValueError, match=_full(message)):
        sf.Answer(
            member_id="member_2",
            text="B",
            raw=None,
            value=None,
            status=status,  # type: ignore[arg-type]
            reason="not_selected",
            signals={},
        )


@pytest.mark.parametrize("reason", ["no_signal", "no_weight"])
def test_the_other_exclude_reasons_stay(reason: str) -> None:
    row = CombineAnswerRow(
        member_id="member_1",
        raw=None,
        value="a",
        status="excluded",
        reason=reason,  # type: ignore[arg-type]
        signals={},
    )

    assert row.reason == reason


def test_an_excluded_row_may_be_not_selected() -> None:
    row = CombineAnswerRow(
        member_id="member_1",
        raw=None,
        value="a",
        status="excluded",
        reason="not_selected",
        signals={},
    )

    assert row.to_dict()["reason"] == "not_selected"


@requires_engine_app
def test_the_case_view_keeps_the_not_selected_reason() -> None:
    case, _ = _fixture_case("rank_vote", _cases()["rank_vote"])

    combined = [answer for answer in case.answers() if answer.member_id == "member_3"]
    assert [(answer.status, answer.reason) for answer in combined] == [("excluded", "not_selected")]


# --- the SDK twin of NR-I1..NR-I5 (each mutation of a pinned Engine case breaks one rule) --------


def _mutated(name: str, change: Any) -> dict[str, Any]:
    wire = copy.deepcopy(_cases()[name])
    change(wire)
    return wire


def _set(path: tuple[Any, ...], value: Any) -> Any:
    def change(wire: dict[str, Any]) -> None:
        node: Any = wire
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return change


def _five_records(wire: dict[str, Any]) -> None:
    wire["narrow"] = [wire["narrow"][0]] * 5


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "change", "match"),
    [
        ("filter_mean", _five_records, _invalid("Combine evidence narrow holds 1 to 4 steps")),
        (
            "filter_mean",
            _set(("narrow", 0, "kept"), ["member_3", "member_1"]),
            _invalid("Combine evidence narrow kept is in author order"),
        ),
        (
            "filter_mean",
            _set(("narrow", 0, "signal"), "Not A Key"),
            _invalid("Combine narrow signal must be a signal key or a declared name"),
        ),
        (
            "filter_mean",
            _set(("narrow", 0, "reduce"), "Filter"),
            _invalid("Combine evidence operators must be pinned ids like 'mode@1'"),
        ),
        (
            "filter_mean",
            _set(("narrow", 0, "scores"), ["member_1"]),
            "Engine evidence narrow[0] scores must be an object with text keys",
        ),
        (
            "rank_vote",
            _set(("narrow", 0, "ranks"), ["member_1"]),
            "Engine evidence narrow[0] ranks must be an object with text keys",
        ),
        (
            "rank_vote",
            _set(("narrow", 0, "ranks", "member_1"), 1.5),
            "Engine evidence narrow[0] ranks must be an integer",
        ),
        (
            "narrow_no_signal",
            _set(
                ("narrow", 1),
                {
                    "reduce": "filter@1",
                    "select": "kept@1",
                    "signal": "field:confidence",
                    "kept": ["member_1", "member_5"],
                    "scores": {"member_1": 1.0, "member_2": 0.0, "member_5": 1.0},
                },
            ),
            _invalid("Combine evidence narrow scores name only the members live then"),
        ),
        (
            "narrow_cut_not_met",
            _set(("narrow", 0, "kept"), []),
            _invalid("Combine evidence only the last narrow step may keep no member"),
        ),
        (
            "filter_mean",
            _set(("members", 1, "status"), "answered"),
            _invalid("Combine answer row has a reason exactly when it did not answer"),
        ),
        (
            "narrow_no_signal",
            _set(("members", 1, "signals", "field:score"), 1.0),
            _invalid("Combine evidence narrow no_signal member has no value for its step's signal"),
        ),
        (
            "narrow_no_votes",
            _set(("result", "reason"), "output_missing"),
            _invalid(
                "Combine evidence narrow abstain ends with no_votes or cut_not_met before the "
                "main step and the gate"
            ),
        ),
    ],
)
def test_the_sdk_refuses_a_narrow_record_that_breaks_a_rule(
    name: str, change: Any, match: str
) -> None:
    _decode_refused(_mutated(name, change), match)


@requires_engine_app
def test_the_sdk_refuses_an_answered_row_that_a_narrow_step_left_out() -> None:
    def change(wire: dict[str, Any]) -> None:
        wire["members"][1].update(status="answered", reason=None)

    _decode_refused(
        _mutated("filter_mean", change),
        _invalid(
            "Combine evidence member a narrow step left out is excluded with not_selected or "
            "no_signal"
        ),
    )


@requires_engine_app
def test_the_sdk_refuses_a_not_selected_row_that_every_step_kept() -> None:
    def change(wire: dict[str, Any]) -> None:
        wire["members"][0].update(status="excluded", reason="not_selected")
        wire["chosen"] = []
        wire["result"] = {
            "member_id": None,
            "value": None,
            "status": "abstain",
            "reason": "no_votes",
        }
        wire["tally"] = None

    _decode_refused(
        _mutated("rank_vote", change),
        _invalid("Combine evidence not_selected member is in no later narrow kept"),
    )


@requires_engine_app
def test_the_sdk_refuses_a_failed_member_in_the_first_kept() -> None:
    def change(wire: dict[str, Any]) -> None:
        wire["members"][0].update(status="fail", reason="empty", value=None)
        wire["dropped"] = 1

    _decode_refused(
        _mutated("filter_mean", change),
        _invalid("Combine evidence kept of the first narrow step names only members that answered"),
    )


@requires_engine_app
def test_the_sdk_narrow_bound_is_the_engine_bound() -> None:
    pinned = json.loads(
        (COMBINE_CONTRACT / "schemas" / "screamingface.combine-evidence.v1.json").read_text(
            encoding="utf-8"
        )
    )
    (as_list,) = [
        branch for branch in pinned["properties"]["narrow"]["anyOf"] if "maxItems" in branch
    ]

    assert MAX_NARROW_STEPS == 4
    assert as_list["maxItems"] == MAX_NARROW_STEPS


@requires_engine_app
def test_every_decoded_record_names_its_reduce_op() -> None:
    reduces = {
        name: [record.reduce for record in _decoded(name).narrow or ()] for name in _EXPECTED_NAMES
    }

    assert reduces["filter_rank_envelope"] == ["filter@1"]
    assert reduces["narrow_no_signal"] == ["filter@1", "by_signal@1"]
    assert reduces["judge_rank_after_filter"] == ["filter@1", "scores@1"]
