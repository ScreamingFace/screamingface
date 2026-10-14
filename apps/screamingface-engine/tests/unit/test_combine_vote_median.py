"""Vote and Median run on the Engine from the SDK-written specs (OME-1289 E4a, unit 5).

FEATURE: ``sf.Vote`` and ``sf.Median`` compile to a combine spec; the Engine runs it with the
built-in operators and no model call.
STORY: as a researcher, I read one member's answer byte for byte, see the tally and the
agreement, and get a loud signal for a tie, an empty answer or a non-number.
WHY the specs come from ``reducer_specs.json``: the SDK writes that file (its drift guard keeps it
current), so these tests prove "the SDK spec runs on the Engine" and never rebuild a spec by hand.

PRD ids: VT-1 .. VT-4, VT-6 .. VT-8, VT-11, VT-14. They are contract pins: the Engine already
delivers the behavior, so they pass on their first run by design. The evidence is the Answer-row
wire (status ``answered|fail``, ``reason``, ``result``, ``dropped``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from combine_support import context_text, run

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_SPECS: dict[str, str] = json.loads(
    (Path(__file__).parent / "data" / "combine_contract" / "reducer_specs.json").read_text("utf-8")
)


def _evidence(name: str, texts: list[str]) -> tuple[str, dict[str, Any]]:
    outcome = run(_SPECS[name], context_text(texts), registry=BUILTIN_OPERATORS)
    return outcome.output, outcome.evidence.model_dump(by_alias=True)


def _tally(evidence: dict[str, Any]) -> list[tuple[str, float, list[str]]]:
    return [(row["value"], row["score"], row["holders"]) for row in evidence["tally"]]


def test_vote_returns_first_holder_text_byte_for_byte_with_tally_and_agreement() -> None:
    texts = ["So the total is 18.\n", "Final: 18", "I computed 26 in the end", "18", "= 18.0 "]
    output, evidence = _evidence("vote_number_5", texts)
    assert output == texts[0]
    assert evidence["tally"] == [
        {"value": "18", "score": 4.0, "holders": ["member_1", "member_2", "member_4", "member_5"]},
        {"value": "26", "score": 1.0, "holders": ["member_3"]},
    ]
    assert evidence["agreement"] == 0.8
    assert evidence["tie"] is False
    assert evidence["built"] is False
    assert evidence["chosen"] == ["member_1"]


def test_vote_tie_goes_to_first_holder_in_author_order_and_flags_tie() -> None:
    texts = ["I say 7", "maybe 9", "7.", "9!"]
    output, evidence = _evidence("vote_number_4", texts)
    assert output == texts[0]
    assert evidence["tie"] is True
    assert evidence["agreement"] == 0.5
    assert [row["value"] for row in evidence["tally"]] == ["7", "9"]

    # VT-D1: the first holder of the first tied value wins, here 9.
    texts = ["9 first", "7", "7", "9"]
    output, evidence = _evidence("vote_number_4", texts)
    assert output == texts[0]
    assert [row["value"] for row in evidence["tally"]] == ["9", "7"]
    assert evidence["tie"] is True


def test_empty_extracts_do_not_vote_and_are_reported() -> None:
    texts = ["no box here", "so \\boxed{5}", "\\boxed{}"]
    output, evidence = _evidence("vote_boxed_3", texts)
    assert output == texts[1]
    assert [member["status"] for member in evidence["members"]] == ["fail", "answered", "fail"]
    assert [member["reason"] for member in evidence["members"]] == ["empty", None, "empty"]
    assert [member["raw"] for member in evidence["members"]] == [None, "5", None]
    assert evidence["dropped"] == 2
    assert evidence["result"] == {
        "member_id": "member_2",
        "value": "5",
        "status": "answered",
        "reason": None,
    }
    assert evidence["agreement"] == 1.0
    assert _tally(evidence) == [("5", 1.0, ["member_2"])]


def test_median_nearest_returns_member_text() -> None:
    texts = ["I think 10", "12", "maybe 30"]
    output, evidence = _evidence("median_nearest_3", texts)
    assert output == texts[1]
    assert evidence["built"] is False
    assert evidence["median"] == "12"
    assert evidence["chosen"] == ["member_2"]
    assert evidence["agreement"] == 1 / 3


def test_median_value_returns_canonical_number_and_built_true() -> None:
    output, evidence = _evidence("median_value_4", ["10", "12", "30", "40"])
    assert output == "21"
    assert evidence["built"] is True
    assert evidence["chosen"] == []
    assert evidence["median"] == "21"
    assert evidence["agreement"] is None


def test_median_skips_non_numeric_members() -> None:
    output, evidence = _evidence("median_line_value_3", ["4", "n/a", "8"])
    assert output == "6"
    member = evidence["members"][1]
    assert (member["raw"], member["value"], member["status"], member["reason"]) == (
        "n/a",
        None,
        "fail",
        "not_numeric",
    )


def test_free_text_vote_uses_exact_normalized_text() -> None:
    output, evidence = _evidence("vote_default_3", ["Paris.", "paris", "Paris, France"])
    assert _tally(evidence) == [
        ("paris", 2.0, ["member_1", "member_2"]),
        ("paris, france", 1.0, ["member_3"]),
    ]
    assert output == "Paris."


def test_single_value_median_single_member_vote_and_median_agreement() -> None:
    _, evidence = _evidence("median_nearest_1", ["5"])
    assert (evidence["chosen"], evidence["agreement"]) == (["member_1"], 1.0)

    _, evidence = _evidence("vote_number_1", ["7"])
    assert (evidence["chosen"], evidence["agreement"], evidence["tie"]) == (
        ["member_1"],
        1.0,
        False,
    )

    _, evidence = _evidence("median_nearest_3", ["9", "9", "12"])
    assert evidence["median"] == "9"
    assert evidence["chosen"] == ["member_1"]
    assert evidence["agreement"] == 2 / 3


def test_benchmark_rule_vote_groups_like_the_grader() -> None:
    # The SDK resolved extract="benchmark" against the gsm8k rule (OME-1289 gap, GP-4): the spec
    # carries the Inspect operators, so "$1,200" and "1200" are one answer and "1,300" another.
    texts = ["The total is $1,200.", "1200", "I get 1,300"]
    output, evidence = _evidence("vote_benchmark_gsm8k_3", texts)

    assert evidence["operators"] == [
        "inspect_number@1",
        "inspect_numeric@1",
        "mode@1",
        "first_holder@1",
    ]
    assert [row["holders"] for row in evidence["tally"]] == [
        ["member_1", "member_2"],
        ["member_3"],
    ]
    assert output == texts[0]
