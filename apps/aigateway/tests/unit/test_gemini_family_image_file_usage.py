"""Gemini and Antigravity report image/file input tokens from `promptTokensDetails` (OME-1546).

FEATURE: image/file token accounting, gateway half.
INVARIANT: totals are unchanged — the field is a non-additive subset of ``prompt_tokens``.
INVARIANT: no breakdown → ``None`` (unknown), never ``0``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from litellm.types.utils import ModelResponse

from aigateway.plugins.antigravity_provider.message_adapter import (
    model_response_from_antigravity,
)
from aigateway.plugins.gemini_provider.message_adapter import model_response_from_gemini

from .test_usage_modalities import RECORDED_GEMINI_USAGE

Builder = Callable[[dict[str, Any], str], ModelResponse]

BUILDERS: list[Builder] = [model_response_from_gemini, model_response_from_antigravity]


def _response(usage: dict[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": "4827"}]}, "finishReason": "STOP"}
        ],
        "modelVersion": "gemini-2.5-flash",
    }
    if usage is not None:
        data["usageMetadata"] = copy.deepcopy(usage)
    return data


def _usage(builder: Builder, data: dict[str, Any]) -> dict[str, Any]:
    return builder(data, "gemini-2.5-flash").model_dump()["usage"]


@pytest.mark.parametrize("builder", BUILDERS, ids=["gemini", "antigravity"])
def test_recorded_breakdown_fills_the_field(builder: Builder) -> None:
    usage = _usage(builder, _response(RECORDED_GEMINI_USAGE))
    assert usage["prompt_tokens_details"]["image_and_file_tokens"] == 1290 + 334
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == (
        1638,
        4,
        1642,
    )


@pytest.mark.parametrize("builder", BUILDERS, ids=["gemini", "antigravity"])
def test_no_breakdown_is_an_explicit_unknown_and_totals_hold(builder: Builder) -> None:
    # The 2026-10-16 Antigravity image call: prompt 1106, no promptTokensDetails.
    usage = _usage(
        builder,
        _response({"promptTokenCount": 1106, "candidatesTokenCount": 2, "totalTokenCount": 1108}),
    )
    assert usage["prompt_tokens_details"] == {"image_and_file_tokens": None}
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == (
        1106,
        2,
        1108,
    )


@pytest.mark.parametrize("builder", BUILDERS, ids=["gemini", "antigravity"])
def test_text_only_breakdown_is_a_known_zero(builder: Builder) -> None:
    usage = _usage(
        builder,
        _response(
            {
                "promptTokenCount": 8,
                "candidatesTokenCount": 1,
                "totalTokenCount": 9,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 8}],
            }
        ),
    )
    assert usage["prompt_tokens_details"]["image_and_file_tokens"] == 0
    assert usage["prompt_tokens"] == 8


@pytest.mark.parametrize("builder", BUILDERS, ids=["gemini", "antigravity"])
def test_wrapped_code_assist_payload_reads_the_inner_usage(builder: Builder) -> None:
    # Code Assist wraps the Gemini body in `response`; the adapters unwrap it first.
    usage = _usage(builder, {"response": _response(RECORDED_GEMINI_USAGE)})
    assert usage["prompt_tokens_details"]["image_and_file_tokens"] == 1624


@pytest.mark.parametrize("builder", BUILDERS, ids=["gemini", "antigravity"])
def test_no_usage_metadata_still_means_no_usage(builder: Builder) -> None:
    # Unchanged behaviour: no usageMetadata means no usage object; the field is not invented.
    assert builder(_response(None), "gemini-2.5-flash").model_dump().get("usage") is None
