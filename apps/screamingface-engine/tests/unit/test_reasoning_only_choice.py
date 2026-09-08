"""A reasoning-only model reply is the MODEL's behavior, not a broken gateway (OME-1126).

FEATURE: truthful failure taxonomy for reasoning models.

STORY: as a researcher whose run just died, the failure must tell me WHO misbehaved.
A live run misfiled qwen3.7-flash's `content: null` + `reasoning_content` reply as
"malformed aigateway response" and sent two days of debugging at the wrong component.

INVARIANT under test: a complete choice that carried reasoning text but no content is
classified `model_empty_content`, its message names the model behavior and finish
reason, and the message survives the report's `public_error` sanitizer verbatim — no
path-like tokens, within the 200-char cap. A choice with NEITHER content NOR reasoning
keeps the existing `aigateway_bad_response` taxonomy (regression pin).
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.aggregation import public_error
from screamingface_engine.runner.errors import RunnerRequestError
from screamingface_engine.runner.model_response import parse_choice, raise_if_unusable


def _payload(message: dict, finish_reason: str = "stop") -> dict:
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def test_reasoning_only_choice_is_classified_as_model_empty_content() -> None:
    choice = parse_choice(
        _payload(
            {
                "content": None,
                "role": "assistant",
                "reasoning_content": "The user provided an empty prompt...",
            }
        )
    )
    with pytest.raises(RunnerRequestError) as exc_info:
        raise_if_unusable(choice)
    assert exc_info.value.code == "model_empty_content"
    message = str(exc_info.value)
    assert "reasoning" in message
    assert "finish_reason=stop" in message


def test_the_model_empty_content_message_survives_the_report_sanitizer() -> None:
    """WHY: `public_error` replaces any path-bearing message with a canned default — the
    exact mechanism that ate this failure's diagnostics in the live hunt. The message
    must reach the report as written."""
    choice = parse_choice(
        _payload({"content": None, "role": "assistant", "reasoning_content": "thinking..."})
    )
    with pytest.raises(RunnerRequestError) as exc_info:
        raise_if_unusable(choice)
    rendered = public_error(
        {"kind": "ResolutionError", "code": exc_info.value.code, "message": str(exc_info.value)},
        default_code="grading_failed",
        default_message="the Benchmark could not grade this Case",
    )
    assert rendered.message == str(exc_info.value)
    assert rendered.code == "model_empty_content"


def test_a_choice_with_neither_content_nor_reasoning_stays_a_gateway_fault() -> None:
    """Regression pin: the pre-existing taxonomy for a truly empty message is unchanged."""
    choice = parse_choice(_payload({"content": None, "role": "assistant"}))
    with pytest.raises(RunnerRequestError) as exc_info:
        raise_if_unusable(choice)
    assert exc_info.value.code == "aigateway_bad_response"


def test_refusal_still_wins_over_the_reasoning_only_classification() -> None:
    """INVARIANT: refusal precedes emptiness — a content-filtered turn carries null text
    by construction and must keep its provider_refusal landing."""
    choice = parse_choice(
        _payload(
            {"content": None, "role": "assistant", "reasoning_content": "hmm", "refusal": "no"}
        )
    )
    with pytest.raises(RunnerRequestError) as exc_info:
        raise_if_unusable(choice)
    assert exc_info.value.code == "provider_refusal"


def test_token_exhaustion_still_wins_over_the_reasoning_only_classification() -> None:
    """INVARIANT: an all-reasoning `length` turn is the token cap's fault, and the cap
    message names the budget to raise — that landing is unchanged."""
    choice = parse_choice(
        _payload(
            {"content": None, "role": "assistant", "reasoning_content": "thinking"},
            finish_reason="length",
        )
    )
    with pytest.raises(RunnerRequestError) as exc_info:
        raise_if_unusable(choice, max_tokens=8192)
    assert exc_info.value.code == "model_token_cap"
