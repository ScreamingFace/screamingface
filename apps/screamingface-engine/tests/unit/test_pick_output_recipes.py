"""SDK-written Pick output recipes run in the engine world (OME-1289 E4b, pick-output: S5, S8).

FEATURE: the url4 files ``recipe_s5_pick_output.url4`` and ``recipe_s8_pick_output.url4`` are what
the SDK compiles for ``sf.Pick("confidence", order="max", output="answer")`` and
``sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer")``. Each test runs
the real compiler output through the mocked gateway of ``_signal_world.run_candidate``.
STORY: as a researcher, the Case answer is the ``answer`` field of the most confident member's
JSON reply, ``42``, and not the whole reply text. A winner without the field abstains.
INVARIANT defended: the Engine answers one field of the chosen member only; a winner without the
field abstains with ``output_missing`` and the runner-up is never used.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"

# request model -> (reply, cost in credits); the most confident member is member_1
_MODELS = {
    "prov/alpha": ('{"answer": 42, "confidence": 0.9}', "0.001"),
    "prov/beta": ('{"answer": 40, "confidence": 0.6}', "0.001"),
    "prov/gamma": ('{"answer": "forty-one", "confidence": 0.3}', "0.001"),
}


def _read(name: str) -> str:
    # WHY inside the test: a missing file fails one test, not the whole collection
    return (_DATA / name).read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["recipe_s5_pick_output.url4", "recipe_s8_pick_output.url4"])
async def test_engine_runs_sdk_pick_output_on_json_replies(name: str) -> None:
    record = await run_candidate(_read(name), _MODELS, "miss")

    synthesis = operation(record, "op_synthesis_1")
    combine = synthesis["combine"]
    assert synthesis["output"] == "42"
    assert combine["reducer"] == "pick"
    assert combine["chosen"] == ["member_1"]
    assert combine["built"] is True
    assert combine["tie"] is False
    assert combine["result"] == {
        "member_id": None,
        "value": "42",
        "status": "answered",
        "reason": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["recipe_s5_pick_output.url4", "recipe_s8_pick_output.url4"])
async def test_engine_run_of_sdk_pick_output_abstains_when_the_winner_lacks_the_field(
    name: str,
) -> None:
    models = {
        **_MODELS,
        "prov/alpha": ('{"confidence": 0.9}', "0.001"),
    }

    record = await run_candidate(_read(name), models, "miss")

    synthesis = operation(record, "op_synthesis_1")
    combine = synthesis["combine"]
    assert synthesis["output"] == ""
    assert combine["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "output_missing",
    }
    assert combine["chosen"] == []
