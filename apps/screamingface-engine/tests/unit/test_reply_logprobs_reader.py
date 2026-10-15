"""The one member reader gives the reply log-probability numbers (E4b part 3, logprob-capture).

Pins LC#6 (b) (a call that asked and got none gives None, one count-only warning), LC#12 (an
ambiguous source or two source calls give None for the logprob keys only), and LC#19 (one reader
returns the accounting and the reply numbers from one fingerprint index). A separate module
(append-only gate).
"""

from __future__ import annotations

import logging

import pytest

from screamingface_engine.operation_accounting import ReplyLogprobs, SignalAccounting
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.world.combine import _read_member_accounting

_KEYS = ("logprob_tokens", "logprob_sum", "entropy_mean")
_UNKNOWN = {key: None for key in _KEYS}
_ASKED = (("logprobs", "true"),)
_FP_A = ("/provider/alpha", _ASKED)
_FP_B = ("/provider/beta", _ASKED)
_FP_C = ("/provider/gamma", _ASKED)
_SIGNALS = SignalAccounting(0.001, 10.0, 5.0, 2.0)
_REPLY = ReplyLogprobs(tokens=3, logprob_sum=-0.6, top_k=5, entropy_mean=0.4)


def _call(
    fingerprint: tuple[str, tuple[tuple[str, str], ...]],
    reply: ReplyLogprobs | None = _REPLY,
) -> OperationCall:
    path, params = fingerprint
    return OperationCall(
        path, params, "an answer", "stop", None, signal_accounting=_SIGNALS, reply_logprobs=reply
    )


def _read(recorded: list[OperationCall], sources: dict) -> dict[str, dict[str, float | None]]:
    with capture_operation_calls() as calls:
        calls.extend(recorded)
        return _read_member_accounting(sources)


def _logprob_part(numbers: dict[str, float | None]) -> dict[str, object]:
    return {key: numbers.get(key, "absent") for key in _KEYS}


def test_member_reader_returns_accounting_and_reply_logprobs() -> None:
    """LC#19: one fingerprint index gives both the accounting and the reply numbers."""
    assert _read([_call(_FP_A)], {"member_1": {"model_1": _FP_A}}) == {
        "member_1": {
            "cost_usd": 0.001,
            "latency_ms": 10.0,
            "tokens_in": 5.0,
            "tokens_out": 2.0,
            "logprob_tokens": 3.0,
            "logprob_sum": -0.6,
            "entropy_mean": 0.4,
        }
    }


def test_absent_logprobs_give_none_and_one_count_warning(caplog: pytest.LogCaptureFixture) -> None:
    """LC#6 (b): a 200 reply without logprobs is a missing value, counted once (P5)."""
    recorded = [_call(_FP_A, reply=None), _call(_FP_B, reply=None), _call(_FP_C)]
    sources = {
        "member_1": {"model_1": _FP_A},
        "member_2": {"model_2": _FP_B},
        "member_3": {"model_3": _FP_C},
    }
    with caplog.at_level(logging.WARNING, logger="screamingface_engine.world.combine"):
        result = _read(recorded, sources)
    assert _logprob_part(result["member_1"]) == _UNKNOWN
    assert _logprob_part(result["member_2"]) == _UNKNOWN
    assert result["member_3"]["logprob_sum"] == -0.6
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        "combine reply logprobs: 2 member(s) asked for logprobs and got none"
    ]


def test_a_call_that_did_not_ask_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """LC#6 (b): a call without `logprobs` gives None and no warning."""
    recorded = [_call(("/provider/alpha", ()), reply=None)]
    sources = {"member_1": {"model_1": ("/provider/alpha", ())}}
    with caplog.at_level(logging.WARNING, logger="screamingface_engine.world.combine"):
        result = _read(recorded, sources)
    assert _logprob_part(result["member_1"]) == _UNKNOWN
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_member_with_ambiguous_source_gets_none() -> None:
    """LC#12 (a): two matches, or zero matches, give None (no guessing)."""
    result = _read(
        [_call(_FP_A), _call(_FP_A)],
        {"member_1": {"model_1": _FP_A}, "member_2": {"model_2": _FP_B}},
    )
    assert _logprob_part(result["member_1"]) == _UNKNOWN
    assert _logprob_part(result["member_2"]) == _UNKNOWN


def test_member_with_two_source_calls_gets_none_for_logprobs_only() -> None:
    """LC#12 (b): two source calls are two replies; the accounting still folds."""
    result = _read(
        [_call(_FP_A), _call(_FP_B)],
        {"member_1": {"model_1": _FP_A, "model_2": _FP_B}},
    )
    assert _logprob_part(result["member_1"]) == _UNKNOWN
    assert result["member_1"]["cost_usd"] == 0.002
    assert result["member_1"]["latency_ms"] == 20.0
