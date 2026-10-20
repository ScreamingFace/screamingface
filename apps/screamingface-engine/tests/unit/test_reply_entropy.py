"""The mean token entropy of one member reply, in nats (E4b part 3, unit 4; entropy PRD §3).

FEATURE: at each position, p_i = exp(l_i) for the first k top entries, r = max(0, 1 - sum p_i),
and H_t = -sum p_i ln p_i - r ln r (0 ln 0 = 0); the reply value is the mean of H_t over the
positions that have top entries.
STORY: as a researcher, I keep the member answer whose tokens were the least uncertain.
INVARIANT defended: the unlisted mass counts (P8); rounding never gives a negative value or -0.0;
one bad top entry makes only the entropy None (LC-D2). Every oracle is hand-computed.
Unit 3 built the formula (D-U3-4), so most rows here are characterization (CHAR) rows.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.world.reply_logprobs import reply_logprobs

_FIXTURE = Path(__file__).parent / "data" / "logprobs" / "openrouter_reply_with_logprobs.json"
LN = math.log


def _reply(positions: Sequence[tuple[float, Sequence[object]]]) -> dict[str, Any]:
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


def _entropy(positions: Sequence[tuple[float, Sequence[object]]]) -> float | None:
    record = reply_logprobs(_reply(positions), 5)
    assert record is not None
    return record.entropy_mean


# --- EN#1: the residual mass counts -------------------------------------------------------------


def test_entropy_with_residual_mass() -> None:
    # p = 0.5, 0.3; r = 0.2: H = 0.5 ln 2 + 0.3 ln(1/0.3) + 0.2 ln 5
    assert _entropy([(-0.7, [LN(0.5), LN(0.3)])]) == pytest.approx(1.0296530140645737, rel=1e-12)


# --- EN#2: the mean over positions (erratum E-2: H = ln 2 and ln 4) -----------------------------


def test_entropy_is_the_mean_over_positions() -> None:
    entropy = _entropy([(-0.7, [LN(0.5), LN(0.5)]), (-1.4, [LN(0.25)] * 4)])
    assert entropy == pytest.approx(1.0397207708399179, rel=1e-12)  # (ln 2 + ln 4) / 2


# --- EN#3: a residual below 0 is clamped to 0 ---------------------------------------------------


def test_entropy_clamps_residual_at_zero() -> None:
    entropy = _entropy([(-0.5, [LN(0.6), LN(0.6)])])  # sum p = 1.2, so r = 0
    assert entropy == pytest.approx(0.6129907485191889, rel=1e-12)  # -1.2 ln 0.6
    assert entropy is not None and math.isfinite(entropy) and entropy >= 0
    # the recorded unit 1 reply: sum p = 1.0000000356, so r = 0
    recorded = reply_logprobs(json.loads(_FIXTURE.read_text(encoding="utf-8"))["body"], 5)
    assert recorded is not None
    assert recorded.entropy_mean == pytest.approx(6.547567880357428e-07, rel=1e-9)


# --- EN#11: the chosen token may be outside the top list ---------------------------------------


def test_entropy_with_the_chosen_token_outside_the_top_list() -> None:
    record = reply_logprobs(_reply([(-3.0, [LN(0.5), LN(0.5)])]), 5)

    assert record is not None
    assert record.entropy_mean == pytest.approx(0.6931471805599453, rel=1e-12)  # ln 2
    assert record.logprob_sum == -3.0
    assert record.tokens == 1


# --- EN#12: one bad top entry makes the entropy None and keeps the logprob ---------------------


@pytest.mark.parametrize("bad", [0.3, float("nan"), float("-inf"), "x", None, True])
def test_bad_top_entry_gives_none_entropy_and_keeps_logprob(bad: object) -> None:
    record = reply_logprobs(_reply([(-0.25, [LN(0.5), bad]), (-0.5, [LN(0.5), LN(0.5)])]), 5)

    assert record is not None
    assert record.entropy_mean is None
    assert record.logprob_sum == -0.75
    assert record.tokens == 2


# --- EN#4: a position without top entries is skipped ---------------------------------------------


def test_entropy_skips_positions_without_top_entries() -> None:
    record = reply_logprobs(_reply([(-0.1, []), (-0.7, [LN(0.5), LN(0.5)])]), 5)
    assert record is not None
    assert record.entropy_mean == pytest.approx(0.6931471805599453, rel=1e-12)
    assert record.tokens == 2
    none_listed = reply_logprobs(_reply([(-0.25, []), (-0.5, [])]), 5)
    assert none_listed is not None
    assert none_listed.entropy_mean is None
    assert none_listed.logprob_sum == -0.75


# --- EN#5: a certain token has entropy 0.0, not -0.0 --------------------------------------------


def test_entropy_of_a_certain_token_is_zero() -> None:
    entropy = _entropy([(0.0, [0.0])])
    assert entropy == 0.0
    assert entropy is not None and math.copysign(1.0, entropy) == 1.0
