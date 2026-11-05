"""The three sf.Logprob forms of one member reply (E4b part 3, unit 4; logprob PRD §3).

FEATURE: ``logprob_value(n, s, form)`` turns a reply's token count n and exact log-probability sum
s into the declared value: "sum" is s, "mean" is s / n, "prob" is exp(s / n).
STORY: as a researcher, I read how sure each member was of its own reply.
INVARIANT defended: no token gives None (LP-D2); "prob" that underflows to 0.0 gives None (P10);
only the content tokens count (LP-D6); the result is never -0.0. Every oracle is hand-computed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.combine.logprob_forms import logprob_value
from screamingface_engine.world.reply_logprobs import reply_logprobs

_FIXTURE = Path(__file__).parent / "data" / "logprobs" / "openrouter_reply_with_logprobs.json"
_FORMS = ("mean", "sum", "prob")


def _reply(positions: Sequence[tuple[float, Sequence[float]]]) -> dict[str, Any]:
    """A gateway reply with synthetic token text (the shape of the unit 1 fixture)."""
    content = [
        {
            "token": f"tok{index}",
            "bytes": list(f"tok{index}".encode()),
            "logprob": logprob,
            "top_logprobs": [
                {
                    "token": f"tok{index}_alt{rank}",
                    "bytes": list(f"tok{index}_alt{rank}".encode()),
                    "logprob": value,
                }
                for rank, value in enumerate(top)
            ],
        }
        for index, (logprob, top) in enumerate(positions)
    ]
    return {
        "choices": [
            {
                "message": {"content": "SYNTHETIC-ANSWER"},
                "finish_reason": "stop",
                "logprobs": {"content": content, "refusal": None},
            }
        ]
    }


# --- LP#1: the three forms ---------------------------------------------------------------------


def test_logprob_forms_mean_sum_prob() -> None:
    record = reply_logprobs(_reply([(-0.1, []), (-0.2, []), (-0.3, [])]), None)

    assert record is not None
    assert record.tokens == 3
    assert record.logprob_sum == -0.6  # math.fsum of the three values
    assert logprob_value(3, record.logprob_sum, "sum") == -0.6
    assert logprob_value(3, record.logprob_sum, "mean") == -0.19999999999999998  # -0.6 / 3
    assert logprob_value(3, record.logprob_sum, "prob") == math.exp(-0.19999999999999998)
    assert logprob_value(3, record.logprob_sum, "prob") == 0.8187307530779818


# --- LP#2: no token gives None -----------------------------------------------------------------


def test_logprob_of_zero_tokens_is_none() -> None:
    for form in _FORMS:
        assert logprob_value(0, 0.0, form) is None
        assert logprob_value(0, None, form) is None
        assert logprob_value(3, None, form) is None
        assert logprob_value(None, -0.5, form) is None
    assert reply_logprobs(_reply([]), None) is None  # LC-E3: an empty content list (unit 3)


# --- LP#3: prob underflow gives None; the edges -------------------------------------------------


def test_logprob_prob_underflow_is_none() -> None:
    assert math.exp(-800.0) == 0.0  # the platform underflows here
    assert logprob_value(1, -800.0, "prob") is None
    assert logprob_value(1, -800.0, "mean") == -800.0
    assert logprob_value(1, -800.0, "sum") == -800.0
    assert logprob_value(1, -700.0, "prob") == math.exp(-700.0)
    assert math.exp(-700.0) > 0.0
    # -0.0 never reaches the evidence
    for form in ("sum", "mean"):
        value = logprob_value(1, -0.0, form)
        assert value == 0.0
        assert value is not None and math.copysign(1.0, value) == 1.0
    # a positive sum or a non-finite number is not a log-probability
    assert logprob_value(1, 0.5, "sum") is None
    assert logprob_value(1, float("-inf"), "sum") is None
    assert logprob_value(float("nan"), -0.5, "sum") is None
    # the recorded unit 1 reply: one token with logprob 0.0, so prob is its upper bound 1.0
    recorded = json.loads(_FIXTURE.read_text(encoding="utf-8"))["body"]
    record = reply_logprobs(recorded, 5)
    assert record is not None
    assert record.tokens == 1
    assert record.logprob_sum == 0.0
    assert logprob_value(record.tokens, record.logprob_sum, "prob") == 1.0


# --- LP#11: only the content tokens count ------------------------------------------------------


def test_logprob_counts_content_tokens_only() -> None:
    data = _reply([(-0.1, []), (-0.2, []), (-0.3, [])])
    message = data["choices"][0]["message"]
    message["reasoning"] = "think"
    message["reasoning_details"] = [{"type": "reasoning.text", "text": "think"}]
    data["choices"][0]["logprobs"]["reasoning"] = [
        {"token": "r", "bytes": [114], "logprob": -5.0, "top_logprobs": []}
    ]

    record = reply_logprobs(data, None)

    assert record is not None
    assert record.tokens == 3
    assert record.logprob_sum == -0.6


# --- LP#4: each form is computed on its own -----------------------------------------------------


def test_logprob_each_form_is_its_own_expression() -> None:
    assert logprob_value(2, -1.0, "sum") == -1.0
    assert logprob_value(2, -1.0, "mean") == -0.5
    assert logprob_value(2, -1.0, "prob") == math.exp(-0.5)
    # the sum and mean keep the +0.0 that turns -0.0 into 0.0; the prob underflow is its own rule
    for form in ("sum", "mean"):
        value = logprob_value(2, -0.0, form)
        assert value is not None and math.copysign(1.0, value) == 1.0
    assert logprob_value(1, -800.0, "prob") is None
    assert logprob_value(1, -800.0, "sum") == -800.0
