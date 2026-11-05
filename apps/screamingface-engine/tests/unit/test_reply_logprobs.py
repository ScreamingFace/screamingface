"""The pure parser of the token log-probability numbers (E4b part 3, logprob-capture).

Pins LC#2 (the parser ignores logprobs in `Choice`), LC#3 (the exact token sum and the recorded
reply), LC#4 (a bad token value erases the sum only), LC#5 (no token text is kept or logged), LC#6
(absent logprobs give None), LC#14 (only the first k top entries count), LC#17 (a bad top entry
erases the entropy only) of `docs/spec/2026-10-15-e4b-signal-sources/prd/logprob-capture.md`.
A separate module (append-only gate).
"""

from __future__ import annotations

import dataclasses
import logging
import math
from typing import Any

import pytest
from logprobs_support import REPLY, fixture

from screamingface_engine.operation_accounting import ReplyLogprobs
from screamingface_engine.world.model_response import Choice, parse_choice
from screamingface_engine.world.reply_logprobs import reply_logprobs

_LN = math.log
_EN1 = 1.0296530140645737


def _entry(logprob: object, tops: list[object] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"token": "secret-token", "bytes": [115], "logprob": logprob}
    if tops is not None:
        entry["top_logprobs"] = [
            {"token": "secret-top", "bytes": [116], "logprob": value} for value in tops
        ]
    return entry


def _reply(*entries: object) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"content": "an answer"},
                "finish_reason": "stop",
                "logprobs": {"content": list(entries)},
            }
        ]
    }


def _two_positions(second_tops: object) -> dict[str, Any]:
    first = {"logprob": -0.5, "top_logprobs": [{"logprob": _LN(0.5)}, {"logprob": _LN(0.3)}]}
    return _reply(first, {"logprob": -0.25, "top_logprobs": second_tops})


def test_parse_choice_ignores_logprobs() -> None:
    """LC#2: the chat decoder keeps its five fields; logprobs never reach `Choice`."""
    assert parse_choice(fixture(REPLY)["body"]) == Choice(
        content="SYNTHETIC-ANSWER",
        tool_calls=None,
        finish_reason="stop",
        refusal=None,
        has_reasoning=False,
    )
    assert [f.name for f in dataclasses.fields(Choice)] == [
        "content",
        "tool_calls",
        "finish_reason",
        "refusal",
        "has_reasoning",
    ]


def test_reply_logprobs_sums_the_content_tokens() -> None:
    """LC#3: the exact `fsum` sum of the three token values is -0.6."""
    assert reply_logprobs(_reply(_entry(-0.1), _entry(-0.2), _entry(-0.3)), None) == ReplyLogprobs(
        tokens=3, logprob_sum=-0.6, top_k=None, entropy_mean=None
    )


def test_reply_logprobs_reads_the_recorded_openrouter_reply() -> None:
    """LC#3: the recorded reply (one token, five top entries, k = 5)."""
    result = reply_logprobs(fixture(REPLY)["body"], 5)
    assert result is not None
    assert (result.tokens, result.logprob_sum, result.top_k) == (1, 0.0, 5)
    # The five top probabilities sum to 1.0000000356 > 1, so the residual is 0 (entropy PRD §3).
    assert result.entropy_mean == pytest.approx(
        17.875 * math.exp(-17.875)
        + 18.625 * math.exp(-18.625)
        + 18.875 * math.exp(-18.875)
        + 19.375 * math.exp(-19.375),
        rel=1e-12,
    )


def test_zero_and_integer_values_are_valid() -> None:
    """LC#3: a token value of 0 and an integer value are valid log-probabilities."""
    assert reply_logprobs(_reply(_entry(0), _entry(-1)), None) == ReplyLogprobs(2, -1.0, None, None)


@pytest.mark.parametrize(
    "bad",
    [float("-inf"), float("inf"), float("nan"), "-0.1", 0.3, True, None, -(10**400)],
    ids=["minus-inf", "inf", "nan", "string", "positive", "bool", "null", "huge-int"],
)
def test_reply_logprobs_token_sum_is_none_for_a_bad_or_positive_value(bad: object) -> None:
    """LC#4: one bad token value makes the sum unknown; the token count stays."""
    assert reply_logprobs(_reply(_entry(-0.1), _entry(bad), _entry(-0.3)), None) == ReplyLogprobs(
        tokens=3, logprob_sum=None, top_k=None, entropy_mean=None
    )


def test_a_missing_value_or_a_non_object_entry_erases_the_sum() -> None:
    """LC#4: a missing value and a non-object entry both give an unknown sum."""
    assert reply_logprobs(_reply(_entry(-0.1), {"token": "x"}), None) == ReplyLogprobs(
        2, None, None, None
    )
    assert reply_logprobs(_reply(_entry(-0.1), "not-an-entry"), None) == ReplyLogprobs(
        2, None, None, None
    )


def test_reply_logprobs_keeps_no_token_text(caplog: pytest.LogCaptureFixture) -> None:
    """LC#5: only four numbers are kept, and no token text reaches the result or the log."""
    assert [f.name for f in dataclasses.fields(ReplyLogprobs)] == [
        "tokens",
        "logprob_sum",
        "top_k",
        "entropy_mean",
    ]
    with caplog.at_level(logging.DEBUG):
        result = reply_logprobs(_reply(_entry(-0.5, [-0.5, -1.0])), 2)
    assert result is not None
    assert "secret" not in repr(result)
    assert "secret" not in caplog.text
    recorded_result = reply_logprobs(fixture(REPLY)["body"], 5)
    assert recorded_result is not None
    assert "tok0" not in repr(recorded_result)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"choices": []},
        {"choices": ["x"]},
        {"choices": [{"message": {"content": "x"}}]},
        {"choices": [{"logprobs": None}]},
        {"choices": [{"logprobs": "x"}]},
        {"choices": [{"logprobs": {"content": None}}]},
        {"choices": [{"logprobs": {"content": []}}]},
        {"choices": [{"logprobs": {"content": "x"}}]},
    ],
)
def test_absent_logprobs_give_none(data: dict[str, Any]) -> None:
    """LC#6: a reply without a usable `content` list gives None, never a failure."""
    assert reply_logprobs(data, 5) is None


def test_top_logprobs_longer_than_k_counts_only_k() -> None:
    """LC#14: only the first k top entries count (Q8)."""
    entry = _entry(-0.5)
    entry["top_logprobs"] = [{"logprob": _LN(0.5)}, {"logprob": _LN(0.3)}, {"logprob": "beyond-k"}]
    r2 = reply_logprobs(_reply(entry), 2)
    assert r2 is not None
    assert r2.top_k == 2
    assert r2.entropy_mean == pytest.approx(_EN1, rel=1e-12)
    third = reply_logprobs(_reply(entry), 3)
    assert third is not None
    assert third.entropy_mean is None


def test_good_top_lists_give_the_mean_entropy() -> None:
    """LC#17: two positions with the same top list give the mean entropy."""
    r = reply_logprobs(_two_positions([{"logprob": _LN(0.5)}, {"logprob": _LN(0.3)}]), 5)
    assert r is not None
    assert (r.tokens, r.logprob_sum, r.top_k) == (2, -0.75, 5)
    assert r.entropy_mean == pytest.approx(_EN1, rel=1e-12)


@pytest.mark.parametrize(
    "second_tops",
    [
        [{"logprob": _LN(0.5)}, {"logprob": "x"}],
        [{"logprob": _LN(0.5)}, {"logprob": 0.3}],
        [{"logprob": float("nan")}],
        [{"logprob": float("-inf")}],
        [{"logprob": None}],
        [{"token": "no-value"}],
        [5],
        "not-a-list",
    ],
    ids=[
        "string",
        "positive",
        "nan",
        "minus-inf",
        "null",
        "missing",
        "not-an-object",
        "not-a-list",
    ],
)
def test_bad_top_entry_erases_entropy_only(second_tops: object) -> None:
    """LC#17: one bad top entry makes only the entropy unknown; the sum stays."""
    assert reply_logprobs(_two_positions(second_tops), 5) == ReplyLogprobs(
        tokens=2, logprob_sum=-0.75, top_k=5, entropy_mean=None
    )


def test_a_position_without_top_entries_is_skipped() -> None:
    """LC#17: an empty or null top list skips its position (EN-D2)."""
    empty = reply_logprobs(_two_positions([]), 5)
    null = reply_logprobs(_two_positions(None), 5)
    assert empty is not None and null is not None
    assert empty.entropy_mean == pytest.approx(_EN1, rel=1e-12)
    assert null.entropy_mean == pytest.approx(_EN1, rel=1e-12)


def test_no_top_k_gives_no_entropy() -> None:
    """LC#17: without `top_logprobs` in the call there is no entropy."""
    assert reply_logprobs(_two_positions([{"logprob": _LN(0.5)}]), None) == ReplyLogprobs(
        2, -0.75, None, None
    )
