"""The signal recipes run offline end to end in the Engine world (E4b part 3, recipes PRD RC#1-6).

FEATURE: each ``combine_contract/recipe_s12..s16.url4`` is what the SDK compiles for one README
signal recipe (the SDK drift guard keeps it byte-equal). Each test runs those bytes through the
mocked gateway of ``_logprob_world.run_logprob_candidate`` and checks the final answer that the
hand-computed oracle gives.
STORY: as a researcher, I copy a signal recipe and trust that it runs: a vote weighted by the
confidence that each member states, a vote weighted by token probability, the answer with the
highest mean log-probability, the answer with the lowest entropy, and a log-probability threshold
before a larger writer.
INVARIANT defended: every declared signal is recorded for every member (Q7); the Engine asks each
member call for logprobs only when the Fusion declares a logprob or entropy source; a value at the
Filter boundary is kept (``>=``); the larger writer still runs when the small model fails.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from _logprob_world import by_model, run_logprob_candidate
from _signal_world import operation

_DATA = Path(__file__).parent / "data" / "combine_contract"
# The Case input that run_logprob_candidate links (test_samples_seed_contract.py:77).
_CASE_INPUT = "what is 2 + 2?"
_ALPHA = "openrouter/openai/gpt-4o-mini"  # member_1 (and the S16 small model)
_BETA = "openrouter/openai/gpt-4.1-mini"  # member_2
_GAMMA = "openrouter/openai/gpt-4.1-nano"  # member_3
_WRITER = "openrouter/openai/gpt-4.1"  # the S16 larger writer
_FINAL = "final answer"


def _recipe(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


def _member_calls(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The calls to the members (every call whose model is not the S16 writer)."""
    return [call for call in seen if call["model"] != _WRITER]


def _envelope(*kept: tuple[str, str]) -> str:
    """The selection envelope of contracts C2: the Case input and the kept texts, canonical JSON."""
    selected = [{"id": member, "text": text} for member, text in kept]
    return json.dumps(
        {"input": _CASE_INPUT, "selected": selected},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_recipe_s12_verbalized_vote() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _recipe("recipe_s12.url4"),
        {_ALPHA: "Confidence: 20\nA", _BETA: "Confidence: 90\nB", _GAMMA: "Confidence: 30\nA"},
        by_model({}),
        seen.append,
    )

    assert record["status"] == "completed"
    # Oracle: the last line reads A, B, A; the weights are the stated numbers, so a = 20 + 30 = 50
    # and b = 90, and B wins. An unweighted vote would pick A.
    assert record["output"] == "Confidence: 90\nB"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert [m["signals"] for m in combine["members"]] == [
        {"conf": 20.0},
        {"conf": 90.0},
        {"conf": 30.0},
    ]
    assert [m["weight"] for m in combine["members"]] == [20.0, 90.0, 30.0]
    assert {row["value"]: (row["score"], row["holders"]) for row in combine["tally"]} == {
        "a": (50.0, ["member_1", "member_3"]),
        "b": (90.0, ["member_2"]),
    }
    assert combine["signal"] == {"key": "conf", "order": None}
    assert combine["declared"]["conf"]["source"] == "verbalized"
    assert combine["declared"]["conf"]["pattern"] == "Confidence: ([0-9]+)"
    assert len(seen) == 3
    assert all("logprobs" not in call and "top_logprobs" not in call for call in seen)


@pytest.mark.asyncio
async def test_recipe_s13_logprob_prob_vote() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _recipe("recipe_s13.url4"),
        {_ALPHA: "A", _BETA: "B", _GAMMA: "A"},
        by_model(
            {
                _ALPHA: [(-2.0, [])],
                _BETA: [(-0.1, []), (-0.2, []), (-0.3, [])],
                _GAMMA: [(-3.0, [])],
            }
        ),
        seen.append,
    )

    # Oracle: prob_1 = exp(-2), prob_2 = exp(mean(-0.1, -0.2, -0.3)) = exp(-0.2), prob_3 = exp(-3).
    # a = prob_1 + prob_3 = 0.18512235160447665, b = 0.8187307530779818, so B wins.
    probs = [0.1353352832366127, 0.8187307530779818, 0.049787068367863944]
    assert record["output"] == "B"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert [m["signals"]["p"] for m in combine["members"]] == [
        pytest.approx(v, rel=1e-12) for v in probs
    ]
    assert [m["weight"] for m in combine["members"]] == [pytest.approx(v, rel=1e-12) for v in probs]
    tally = {row["value"]: (row["score"], row["holders"]) for row in combine["tally"]}
    assert tally["a"] == (pytest.approx(0.18512235160447665, rel=1e-12), ["member_1", "member_3"])
    assert tally["b"] == (pytest.approx(0.8187307530779818, rel=1e-12), ["member_2"])
    assert combine["signal"] == {"key": "p", "order": None}
    assert combine["declared"] == {"p": {"source": "logprob", "form": "prob"}}
    assert len(seen) == 3
    assert all(call["logprobs"] is True and "top_logprobs" not in call for call in seen)


@pytest.mark.asyncio
async def test_recipe_s14_logprob_argmax() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _recipe("recipe_s14.url4"),
        {_ALPHA: "alpha answer", _BETA: "beta answer", _GAMMA: "gamma answer"},
        by_model(
            {
                _ALPHA: [(-0.9, [])],
                _BETA: [(-0.2, []), (-0.2, []), (-0.2, []), (-0.2, []), (-0.2, [])],
                _GAMMA: [(-0.5, []), (-0.5, [])],
            }
        ),
        seen.append,
    )

    # Oracle: the means are -0.9, -0.2 and -0.5, so member_2 has the maximum. The sums are -0.9,
    # -1.0 and -1.0: a `sum` pick would choose member_1, so the test proves the `mean` form.
    assert record["status"] == "completed"
    assert record["output"] == "beta answer"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "pick")
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"
    assert [m["signals"]["lp"] for m in combine["members"]] == [
        pytest.approx(-0.9, rel=1e-12),
        pytest.approx(-0.2, rel=1e-12),
        pytest.approx(-0.5, rel=1e-12),
    ]
    assert combine["signal"] == {"key": "lp", "order": "max"}
    assert combine["declared"] == {"lp": {"source": "logprob", "form": "mean"}}
    assert len(seen) == 3
    assert all(call["logprobs"] is True and "top_logprobs" not in call for call in seen)


@pytest.mark.asyncio
async def test_recipe_s15_entropy_argmin() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _recipe("recipe_s15.url4"),
        {_ALPHA: "alpha answer", _BETA: "beta answer", _GAMMA: "gamma answer"},
        by_model(
            {
                _ALPHA: [(math.log(0.5), [math.log(0.5), math.log(0.3)])],
                _BETA: [(0.0, [0.0])],
                _GAMMA: [(math.log(0.5), [math.log(0.5), math.log(0.5)])],
            }
        ),
        seen.append,
    )

    # Oracle (entropy PRD §3): member_1 has H = 0.5 ln 2 + 0.3 ln(1/0.3) + 0.2 ln 5 (the residual
    # 0.2 is the missing mass); member_2 has H = 0; member_3 has H = ln 2. The minimum is member_2.
    assert record["status"] == "completed"
    assert record["output"] == "beta answer"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"
    entropies = [m["signals"]["ent"] for m in combine["members"]]
    assert entropies[0] == pytest.approx(1.0296530140645737, rel=1e-12)
    assert entropies[1] == pytest.approx(0.0, abs=1e-12)
    assert entropies[2] == pytest.approx(0.6931471805599453, rel=1e-12)
    assert combine["signal"] == {"key": "ent", "order": "min"}
    assert combine["declared"] == {"ent": {"source": "entropy", "top_logprobs": 5}}
    assert len(seen) == 3
    assert all(call["logprobs"] is True and call["top_logprobs"] == 5 for call in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tokens", "mean", "kept"),
    [((-0.1, -0.1), -0.1, True), ((-0.3,), -0.3, True), ((-0.5,), -0.5, False)],
    ids=["above", "at-threshold", "below"],
)
async def test_recipe_s16_logprob_threshold_records_values(
    tokens: tuple[float, ...], mean: float, kept: bool
) -> None:
    seen: list[dict[str, Any]] = []
    record = await run_logprob_candidate(
        _recipe("recipe_s16.url4"),
        {_ALPHA: "small answer", _WRITER: _FINAL},
        by_model({_ALPHA: [(value, []) for value in tokens]}),
        seen.append,
    )

    # Oracle: the means are -0.1, -0.3 and -0.5. The Filter `>= -0.3` keeps the first two (the
    # boundary is kept) and drops the third. The writer runs in all three cases (RC-D2, N2).
    assert record["status"] == "completed"
    assert record["output"] == _FINAL
    combine = operation(record, "op_synthesis_1")["combine"]
    member = combine["members"][0]
    assert member["signals"] == {"lp": pytest.approx(mean, rel=1e-12)}
    assert member["score"] == (1.0 if kept else 0.0)
    assert combine["chosen"] == (["member_1"] if kept else [])
    assert combine["declared"] == {"lp": {"source": "logprob", "form": "mean"}}
    writer_calls = [call for call in seen if call["model"] == _WRITER]
    assert len(writer_calls) == 1  # the larger model still runs
    expected = (
        _envelope(("member_1", "small answer"))
        if kept
        else '{"input":"what is 2 + 2?","selected":[]}'
    )
    assert writer_calls[0]["messages"][-1]["content"] == expected
    assert "logprobs" not in writer_calls[0]  # only Fusion members ask for logprobs
    assert [call["logprobs"] for call in _member_calls(seen)] == [True]
    if not kept:
        assert combine["result"]["status"] == "abstain"
        assert combine["result"]["reason"] == "no_votes"
