"""``image_and_file_tokens`` is published only inside a valid ``prompt_tokens`` (OME-1546).

FEATURE: image/file token accounting, gateway half — PR #1481 review fix.
INVARIANT: the detail is a NON-ADDITIVE subset of ``prompt_tokens``: it is a known integer only
when ``usageMetadata.promptTokenCount`` is a bounded non-negative int AND
``0 <= media <= promptTokenCount``; otherwise it is ``None`` (unknown).
INVARIANT: the gate touches only the detail — ``prompt_tokens`` keeps its existing lenient
parsing (prior tests and callers depend on it).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from litellm.types.utils import ModelResponse

from aigateway.core.usage_modalities import (
    bounded_image_and_file_tokens_from_gemini,
    prompt_token_total_from_gemini,
)
from aigateway.plugins.antigravity_provider.message_adapter import (
    model_response_from_antigravity,
)
from aigateway.plugins.gemini_provider.message_adapter import model_response_from_gemini

Builder = Callable[[dict[str, Any], str], ModelResponse]

BUILDERS: list[Builder] = [model_response_from_gemini, model_response_from_antigravity]
BUILDER_IDS = ["gemini", "antigravity"]

_ABSENT = object()
_MAX = 2**53 - 1

# WHY these: each one was accepted by the lenient `int(x or 0)` total parser and let the
# detail outlive or exceed its enclosing total (HupBaHa probes on PR #1481).
INVALID_PROMPT_TOTALS: list[Any] = [_ABSENT, None, True, False, 4.0, "4", -1, _MAX + 1]
INVALID_IDS = [
    "absent",
    "null",
    "bool-true",
    "bool-false",
    "float",
    "string",
    "negative",
    "overflow",
]


def _usage_metadata(prompt_total: Any, image: int = 1) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "candidatesTokenCount": 1,
        "totalTokenCount": 9,
        "promptTokensDetails": [
            {"modality": "TEXT", "tokenCount": 2},
            {"modality": "IMAGE", "tokenCount": image},
        ],
    }
    if prompt_total is not _ABSENT:
        usage["promptTokenCount"] = prompt_total
    return usage


def _response(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}
        ],
        "modelVersion": "gemini-2.5-flash",
        "usageMetadata": copy.deepcopy(usage),
    }


def _usage(builder: Builder, usage: dict[str, Any]) -> dict[str, Any]:
    return builder(_response(usage), "gemini-2.5-flash").model_dump()["usage"]


class TestPromptTotalParser:
    @pytest.mark.parametrize("value", [0, 1, 1638, _MAX], ids=["zero", "one", "recorded", "max"])
    def test_bounded_non_negative_int_is_known(self, value: int) -> None:
        assert prompt_token_total_from_gemini({"promptTokenCount": value}) == value

    @pytest.mark.parametrize("value", INVALID_PROMPT_TOTALS, ids=INVALID_IDS)
    def test_anything_else_is_unknown(self, value: Any) -> None:
        usage = {} if value is _ABSENT else {"promptTokenCount": value}
        assert prompt_token_total_from_gemini(usage) is None

    def test_not_a_mapping_is_unknown(self) -> None:
        assert prompt_token_total_from_gemini(None) is None
        assert prompt_token_total_from_gemini([]) is None


class TestBoundedDetail:
    @pytest.mark.parametrize("value", INVALID_PROMPT_TOTALS, ids=INVALID_IDS)
    def test_invalid_prompt_total_makes_detail_unknown(self, value: Any) -> None:
        assert bounded_image_and_file_tokens_from_gemini(_usage_metadata(value, image=0)) is None

    def test_media_larger_than_prompt_total_is_unknown(self) -> None:
        assert bounded_image_and_file_tokens_from_gemini(_usage_metadata(3, image=4)) is None

    def test_media_equal_to_prompt_total_is_known(self) -> None:
        # Boundary: an image-only prompt — the subset may equal the whole.
        usage = {
            "promptTokenCount": 4,
            "promptTokensDetails": [{"modality": "IMAGE", "tokenCount": 4}],
        }
        assert bounded_image_and_file_tokens_from_gemini(usage) == 4

    def test_media_within_prompt_total_is_known(self) -> None:
        assert bounded_image_and_file_tokens_from_gemini(_usage_metadata(8, image=5)) == 5

    def test_unknown_breakdown_stays_unknown_with_a_valid_total(self) -> None:
        assert bounded_image_and_file_tokens_from_gemini({"promptTokenCount": 8}) is None


@pytest.mark.parametrize("builder", BUILDERS, ids=BUILDER_IDS)
class TestAdaptersGateTheDetail:
    @pytest.mark.parametrize("value", INVALID_PROMPT_TOTALS, ids=INVALID_IDS)
    def test_invalid_prompt_total_publishes_none(self, builder: Builder, value: Any) -> None:
        usage = _usage(builder, _usage_metadata(value, image=0))
        assert usage["prompt_tokens_details"] == {"image_and_file_tokens": None}

    def test_prompt_total_smaller_than_media_publishes_none(self, builder: Builder) -> None:
        usage = _usage(builder, _usage_metadata(3, image=4))
        assert usage["prompt_tokens_details"]["image_and_file_tokens"] is None
        # INVARIANT: the total itself is reported exactly as before.
        assert usage["prompt_tokens"] == 3

    def test_valid_total_bounding_media_publishes_the_detail(self, builder: Builder) -> None:
        usage = _usage(builder, _usage_metadata(8, image=5))
        assert usage["prompt_tokens_details"]["image_and_file_tokens"] == 5
        assert usage["prompt_tokens"] == 8

    def test_absent_prompt_total_keeps_the_existing_zero_total(self, builder: Builder) -> None:
        # WHY: the detail gate must not change how `prompt_tokens` is reported to callers.
        usage = _usage(builder, _usage_metadata(_ABSENT, image=1))
        assert usage["prompt_tokens"] == 0
        assert usage["prompt_tokens_details"]["image_and_file_tokens"] is None
