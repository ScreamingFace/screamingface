"""Weighted Vote runs on the Engine from the SDK-written specs (OME-1289 E4a, unit 7).

FEATURE: ``sf.Vote(weights=...)`` compiles to ``weighted_mode@1`` + ``max_weight_holder@1`` with a
weight per member; the Engine sums the weights per answer and picks the heaviest holder.
STORY: as a researcher, I make some members count more, and the report shows each member's weight
and each answer's summed score.
WHY the specs come from ``weighted_vote_specs.json``: the SDK writes that file (its drift guard
keeps it current), so these tests prove "the SDK spec runs on the Engine" and never build a spec by
hand.

PRD ids: WV-1/WV-3/WV-8 are SDK-side. Here: WV-2, WV-4, WV-5, WV-6, WV-7, WV-9 (WV-H1, WV-H2,
WV-D1, WV-D2, WV-D3, WV-D4, WV-E3). They are contract pins: units 1-3 already deliver the behavior,
so they pass on their first run by design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from combine_support import context_text, request, run

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.core.errors import ResolutionError

_SPECS: dict[str, str] = json.loads(
    (Path(__file__).parent / "data" / "combine_contract" / "weighted_vote_specs.json").read_text(
        "utf-8"
    )
)


def _evidence(name: str, texts: list[str]) -> tuple[str, dict[str, Any]]:
    outcome = run(_SPECS[name], context_text(texts), registry=BUILTIN_OPERATORS)
    return outcome.output, outcome.evidence.model_dump(by_alias=True)


def _tally(evidence: dict[str, Any]) -> list[tuple[str, float, list[str]]]:
    return [(row["value"], row["score"], row["holders"]) for row in evidence["tally"]]


def test_weighted_vote_sums_weights_and_picks_highest_weight_holder() -> None:
    texts = ["9", "9", "12", "12", "12"]
    output, evidence = _evidence("weighted_5", texts)
    assert _tally(evidence) == [
        ("9", 6.0, ["member_1", "member_2"]),
        ("12", 3.0, ["member_3", "member_4", "member_5"]),
    ]
    # Both holders of 9 weigh 3.0, so the first in author order is chosen.
    assert evidence["chosen"] == ["member_1"]
    assert output == texts[0]
    assert evidence["agreement"] == 6 / 9
    assert evidence["tie"] is False
    assert [member["weight"] for member in evidence["members"]] == [3.0, 3.0, 1.0, 1.0, 1.0]
    assert [member["score"] for member in evidence["members"]] == [None] * 5

    # WV-H2: the heavier holder of the winning value is chosen.
    texts = ["9", "9"]
    output, evidence = _evidence("weighted_2", texts)
    assert evidence["chosen"] == ["member_2"]
    assert output == texts[1]


def test_score_tie_uses_author_order_and_flags_tie() -> None:
    _, evidence = _evidence("weighted_tie_3", ["9", "12", "12"])
    assert [row["score"] for row in evidence["tally"]] == [2.0, 2.0]
    assert [row["value"] for row in evidence["tally"]] == ["9", "12"]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["tie"] is True
    assert evidence["agreement"] == 0.5

    # WV-D2: two holders with equal top weight, the first in author order is chosen.
    _, evidence = _evidence("weighted_holders_3", ["9", "9", "9"])
    assert evidence["chosen"] == ["member_2"]


def test_weighted_sums_use_decimal_and_are_order_independent() -> None:
    # Float sums would give 0.1 + 0.2 + 0.3 = 0.6000000000000001, which is not equal to 0.6.
    texts = ["5", "5", "5", "7"]
    _, evidence = _evidence("weighted_decimal_4", texts)
    assert [row["score"] for row in evidence["tally"]] == [0.6, 0.6]
    assert evidence["tie"] is True
    assert evidence["chosen"] == ["member_3"]

    _, evidence = _evidence("weighted_decimal_reversed_4", texts)
    assert [row["score"] for row in evidence["tally"]] == [0.6, 0.6]
    assert evidence["tie"] is True
    assert evidence["chosen"] == ["member_1"]


def test_empty_extract_weight_does_not_count() -> None:
    _, evidence = _evidence("weighted_empty_4", ["no number", "9", "7", "7"])
    assert _tally(evidence) == [
        ("7", 2.0, ["member_3", "member_4"]),
        ("9", 1.0, ["member_2"]),
    ]
    first = evidence["members"][0]
    assert (first["status"], first["weight"], first["score"]) == ("empty", 5.0, None)
    assert evidence["agreement"] == 2 / 3
    assert evidence["chosen"] == ["member_3"]
    assert evidence["tie"] is False


def test_engine_accepts_a_weight_at_the_cap() -> None:
    # D-7: the cap is sys.float_info.max / 256, so a sum over 256 such weights stays finite.
    output, evidence = _evidence("weighted_cap_2", ["9", "9"])
    cap = sys.float_info.max / 256
    assert output == "9"
    assert [member["weight"] for member in evidence["members"]] == [cap, cap]
    assert _tally(evidence) == [("9", cap * 2, ["member_1", "member_2"])]
    assert evidence["chosen"] == ["member_1"]


def _without_member_5(spec: dict[str, Any]) -> None:
    del spec["weights"]["member_5"]


def _zero_weight(spec: dict[str, Any]) -> None:
    spec["weights"]["member_1"] = 0


def _negative_weight(spec: dict[str, Any]) -> None:
    spec["weights"]["member_1"] = -1


def _null_weights(spec: dict[str, Any]) -> None:
    spec["weights"] = None


def _extra_member_weight(spec: dict[str, Any]) -> None:
    spec["weights"]["member_6"] = 1.0


def _bad_weights_texts() -> dict[str, str]:
    base = _SPECS["weighted_5"]
    texts: dict[str, str] = {}
    for name, mutate in {
        "missing_member": _without_member_5,
        "zero": _zero_weight,
        "negative": _negative_weight,
        # weighted_mode@1 stays in the spec, so the operator itself finds no weights.
        "null_weights": _null_weights,
        "extra_member": _extra_member_weight,
    }.items():
        spec = json.loads(base)
        mutate(spec)
        texts[name] = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    assert '"member_1":3.0' in base
    texts["nan"] = base.replace('"member_1":3.0', '"member_1":NaN')
    # Finite, but above the Engine cap (sys.float_info.max / 256).
    texts["above_cap"] = base.replace('"member_1":3.0', '"member_1":1e308')
    texts["overflow"] = base.replace('"member_1":3.0', '"member_1":1e309')
    return texts


@pytest.mark.parametrize("name", list(_bad_weights_texts()))
def test_endpoint_rejects_spec_with_bad_weights(name: str) -> None:
    text = _bad_weights_texts()[name]
    with capture_operation_calls() as calls, pytest.raises(ResolutionError) as caught:
        CombineRoute(BUILTIN_OPERATORS)(request(text, context_text(["9", "9", "12", "12", "12"])))
    assert caught.value.code == "combine_spec_invalid"
    assert caught.value.permanent is True
    assert list(calls) == []
