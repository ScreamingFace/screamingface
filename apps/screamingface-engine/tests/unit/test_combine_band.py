"""The abstain band of a vote gate: the spec key ``gate.abstain_band`` (E4b part 6, unit 3).

FEATURE: a vote gate may hold a closed band ``[lo, hi]``. Inside the band the Case abstains;
outside it the gate compares as in part 5 (abstain-band PRD, ans:Q2). This unit parses the key.
STORY: as a benchmark author, I write ``"abstain_band": [lo, hi]`` on a vote gate, and the Engine
parses it, or refuses it with a fixed message that holds no value.
INVARIANT defended: a spec or an evidence without a band keeps its part 5 bytes; a band is two
finite numbers ``lo <= hi`` (``0 <= lo <= hi <= 1`` for an agreement gate); an explicit null is
refused; a refusal names the rule and never echoes a value; the schema id does not change.
AIDEV-NOTE: unit 4 (band-record) appends its tests (AB#4-11, the evidence half of AB#15) below the
last marker of this file. Do not edit the tests above that marker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import spec_text

from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, GateSpec, parse_spec

_DATA = Path(__file__).parent / "data" / "combine_contract"
SCHEMAS = _DATA / "schemas"

# test-plan §6 L37: the five part 5 gate cases. A fixed tuple, never the file: units 1 and 4 of
# this part add cases to the same file.
L37_GATE_CASES = (
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
)
# test-plan §6 L47: the four part 5 gate url4 files. A fixed tuple, never a glob.
L47_GATE_FILES = (
    "gate_abstain_vote_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
    "gate_writer_vote_candidate.url4",
)
_PART_5_GATE_KEYS = ["observe", "observed", "cmp", "threshold", "passed", "branch", "otherwise"]
_SPEC_START = '{"extract":'  # canonical JSON sorts the keys, so every spec starts here
_CONF = {"pattern": "Confidence: ([0-9]+)", "source": "verbalized"}
_INVALID_OBJECT = "gate must be a valid gate object"
_NOT_A_PAIR = "gate abstain_band must be a pair when present"
_LO_ABOVE_HI = "a gate abstain_band needs lo <= hi"
_AGREEMENT_RANGE = "an agreement gate abstain_band is between 0 and 1"
# The numbers and words of the refused bands below. No refusal message may hold one of them.
_ECHO = ("0.75", "1.5", "0.7", "0.6", "0.5", "0.1", "True", "true")


def _band_gate(lo: float, hi: float, threshold: float, otherwise: str) -> dict[str, Any]:
    """The PRD's ``band(lo, hi, threshold, otherwise)``: an agreement ``>=`` gate with a band."""
    return {
        "observe": "agreement",
        "cmp": ">=",
        "threshold": threshold,
        "otherwise": otherwise,
        "abstain_band": [lo, hi],
    }


def _vote_with_band(band: Any) -> dict[str, Any]:
    """Fixture B's vote spec with the AB-1 gate, its band value replaced by ``band`` (any JSON)."""
    return {
        **builtin_vote_spec(3),
        "gate": {**_band_gate(0.6, 0.7, 0.7, "abstain"), "abstain_band": band},
    }


def _bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _spec_failure(spec: dict[str, Any]) -> str:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(spec_text(spec))
    assert caught.value.code == "combine_spec_invalid"
    return str(caught.value)


def _combine_specs(text: str) -> list[str]:
    """Every combine spec text in one url4 file (a spec may sit in a quoted loop body)."""
    decoder = json.JSONDecoder()
    specs: list[str] = []
    start = text.find(_SPEC_START)
    while start != -1:
        _, end = decoder.raw_decode(text, start)
        specs.append(text[start:end])
        start = text.find(_SPEC_START, end)
    return specs


def _pinned(schema_id: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{schema_id}.json").read_text(encoding="utf-8"))


# --- AB#1: the part 5 gate records and gate specs have no band (CHAR) --------------------------


def test_part_5_gate_records_and_specs_have_no_band() -> None:
    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name in L37_GATE_CASES:
        wire = cases[name]
        assert list(wire["gate"]) == _PART_5_GATE_KEYS, name
        dumped = CombineEvidence.model_validate(copy.deepcopy(wire)).model_dump(
            mode="json", by_alias=True
        )
        assert _bytes(dumped) == _bytes(wire), name

    for name in L47_GATE_FILES:
        specs = _combine_specs((_DATA / name).read_text(encoding="utf-8"))
        assert len(specs) == 1, name
        assert '"abstain_band"' not in specs[0], name
        gate = parse_spec(specs[0]).gate
        assert gate is not None, name
        assert getattr(gate, "abstain_band", None) is None, name
        assert "abstain_band" not in gate.model_fields_set, name


# --- AB#2: the Engine parses a gate band -------------------------------------------------------


def test_engine_parses_a_gate_band() -> None:
    parsed = parse_spec(
        spec_text({**builtin_vote_spec(3), "gate": _band_gate(0.6, 0.7, 0.7, "abstain")})
    ).gate
    assert parsed is not None
    assert parsed == GateSpec(
        observe="agreement", cmp=">=", threshold=0.7, otherwise="abstain", abstain_band=[0.6, 0.7]
    )
    assert parsed.abstain_band == [0.6, 0.7]
    assert "abstain_band" in parsed.model_fields_set

    point = parse_spec(spec_text(_vote_with_band([0.5, 0.5]))).gate
    assert point is not None
    assert point.abstain_band == [0.5, 0.5]

    whole = parse_spec(spec_text(_vote_with_band([0, 1]))).gate
    assert whole is not None
    band = whole.abstain_band
    assert band == [0.0, 1.0]
    assert band is not None
    assert [type(edge) for edge in band] == [float, float]

    # P8: no rule ties the band to the threshold (0.7 is above this band).
    low = parse_spec(spec_text(_vote_with_band([0.1, 0.2]))).gate
    assert low is not None
    assert low.abstain_band == [0.1, 0.2]

    # AB-E1, last sentence: a chosen:<name> band is not limited to [0, 1].
    chosen = parse_spec(
        spec_text(
            {
                **builtin_vote_spec(3),
                "signals": {"conf": dict(_CONF)},
                "gate": {
                    "observe": "chosen:conf",
                    "cmp": ">=",
                    "threshold": 80,
                    "otherwise": "abstain",
                    "abstain_band": [-5.0, 1.5],
                },
            }
        )
    ).gate
    assert chosen == GateSpec(
        observe="chosen:conf",
        cmp=">=",
        threshold=80.0,
        otherwise="abstain",
        abstain_band=[-5.0, 1.5],
    )

    plain_gate = _band_gate(0.6, 0.7, 0.7, "abstain")
    del plain_gate["abstain_band"]
    plain = parse_spec(spec_text({**builtin_vote_spec(3), "gate": plain_gate})).gate
    assert plain is not None
    assert plain.abstain_band is None
    assert "abstain_band" not in plain.model_fields_set


# --- AB#3: bad bands are refused, and the message echoes no value ------------------------------


@pytest.mark.parametrize(
    ("band", "rule"),
    [
        pytest.param(None, _NOT_A_PAIR, id="explicit-null"),
        pytest.param([0.75, 0.7], _LO_ABOVE_HI, id="lo-above-hi"),
        pytest.param([0.6], _INVALID_OBJECT, id="one-number"),
        pytest.param([0.1, 0.2, 0.3], _INVALID_OBJECT, id="three-numbers"),
        pytest.param(["a", 0.7], _INVALID_OBJECT, id="a-string"),
        pytest.param([True, 0.7], _INVALID_OBJECT, id="a-bool"),
        pytest.param([0.5, 1.5], _AGREEMENT_RANGE, id="agreement-above-one"),
        pytest.param([-0.1, 0.5], _AGREEMENT_RANGE, id="agreement-below-zero"),
    ],
)
def test_engine_refuses_bad_bands_without_echo(band: Any, rule: str) -> None:
    message = _spec_failure(_vote_with_band(band))

    assert rule in message
    for value in _ECHO:
        assert value not in message


@pytest.mark.parametrize(
    ("edge", "rule"),
    [
        pytest.param("1e400", _INVALID_OBJECT, id="overflows-to-infinity"),
        pytest.param("-1e400", _INVALID_OBJECT, id="overflows-to-minus-infinity"),
        pytest.param("NaN", "combine spec is not valid JSON", id="nan"),
        pytest.param("Infinity", "combine spec is not valid JSON", id="infinity"),
    ],
)
def test_engine_refuses_a_band_that_is_not_finite_without_echo(edge: str, rule: str) -> None:
    good = spec_text(_vote_with_band([0.6, 0.7]))
    assert good.count("[0.6,0.7]") == 1
    text = good.replace("[0.6,0.7]", f"[{edge},0.7]")

    with pytest.raises(SpecInvalid) as caught:
        parse_spec(text)

    assert caught.value.code == "combine_spec_invalid"
    assert rule in str(caught.value)
    assert edge not in str(caught.value)


# --- AB#15 (spec v1 half): the spec schema snapshot holds the band (PIN) -----------------------


def test_spec_schema_snapshot_holds_the_band() -> None:
    assert COMBINE_SPEC_SCHEMA == "screamingface.combine-spec.v1"
    gate_spec = _pinned(COMBINE_SPEC_SCHEMA)["$defs"]["GateSpec"]

    assert gate_spec["properties"].get("abstain_band") == {
        "anyOf": [
            {"items": {"type": "number"}, "maxItems": 2, "minItems": 2, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
        "title": "Abstain Band",
    }
    assert gate_spec["required"] == ["observe", "cmp", "threshold", "otherwise"]
    assert gate_spec["additionalProperties"] is False
    assert list(GateSpec.model_fields) == [
        "observe",
        "cmp",
        "threshold",
        "otherwise",
        "abstain_band",
    ]


# --- unit 4 (band-record) appends its tests below this line ------------------------------------
