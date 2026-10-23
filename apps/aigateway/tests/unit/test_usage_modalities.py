"""Image and file input tokens in the caller's usage object (OME-1546, gateway half).

FEATURE: image/file token accounting. The field is a non-additive subset of ``prompt_tokens``:
a known integer only when the provider reported a per-modality breakdown, ``None`` (unknown)
otherwise — never a guessed ``0``.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.usage_modalities import (
    IMAGE_AND_FILE_KEY,
    image_and_file_tokens_from_gemini,
)

# WHY a recorded shape and not a live call: the direct Gemini API route cannot be exercised from
# the live harness. This is the documented `GenerateContentResponse.usageMetadata` shape
# (ai.google.dev, `UsageMetadata.promptTokensDetails: ModalityTokenCount[]`) for one text prompt,
# one PNG and one one-page PDF.
RECORDED_GEMINI_USAGE: dict[str, Any] = {
    "promptTokenCount": 1638,
    "candidatesTokenCount": 4,
    "totalTokenCount": 1642,
    "promptTokensDetails": [
        {"modality": "TEXT", "tokenCount": 14},
        {"modality": "IMAGE", "tokenCount": 1290},
        {"modality": "DOCUMENT", "tokenCount": 334},
    ],
    "candidatesTokensDetails": [{"modality": "TEXT", "tokenCount": 4}],
}


class TestGeminiModalityParser:
    def test_recorded_breakdown_sums_image_and_document(self) -> None:
        assert image_and_file_tokens_from_gemini(RECORDED_GEMINI_USAGE) == 1290 + 334

    def test_text_only_breakdown_is_a_known_zero(self) -> None:
        usage = {"promptTokensDetails": [{"modality": "TEXT", "tokenCount": 9}]}
        assert image_and_file_tokens_from_gemini(usage) == 0

    def test_other_media_modalities_are_not_counted(self) -> None:
        usage = {
            "promptTokensDetails": [
                {"modality": "AUDIO", "tokenCount": 40},
                {"modality": "VIDEO", "tokenCount": 70},
                {"modality": "image", "tokenCount": 5},
            ]
        }
        assert image_and_file_tokens_from_gemini(usage) == 5

    def test_repeated_modalities_accumulate(self) -> None:
        usage = {
            "promptTokensDetails": [
                {"modality": "IMAGE", "tokenCount": 258},
                {"modality": "IMAGE", "tokenCount": 258},
            ]
        }
        assert image_and_file_tokens_from_gemini(usage) == 516

    def test_missing_token_count_is_proto3_zero(self) -> None:
        # proto3 JSON omits a zero-valued field, so an entry with no count reports zero.
        usage = {"promptTokensDetails": [{"modality": "IMAGE"}, {"modality": "TEXT"}]}
        assert image_and_file_tokens_from_gemini(usage) == 0

    @pytest.mark.parametrize(
        "usage",
        [
            {},
            {"promptTokenCount": 1106, "candidatesTokenCount": 4},
            {"promptTokensDetails": None},
            {"promptTokensDetails": []},
            {"promptTokensDetails": {"modality": "IMAGE", "tokenCount": 3}},
        ],
        ids=["empty", "no-breakdown", "null", "empty-list", "not-a-list"],
    )
    def test_no_breakdown_is_unknown_never_zero(self, usage: dict[str, Any]) -> None:
        assert image_and_file_tokens_from_gemini(usage) is None

    @pytest.mark.parametrize(
        "entry",
        [
            "IMAGE",
            {"tokenCount": 3},
            {"modality": 7, "tokenCount": 3},
            {"modality": "IMAGE", "tokenCount": -1},
            {"modality": "IMAGE", "tokenCount": True},
            {"modality": "IMAGE", "tokenCount": "3"},
            {"modality": "IMAGE", "tokenCount": 3.0},
            {"modality": "TEXT", "tokenCount": None},
        ],
        ids=[
            "not-an-object",
            "no-modality",
            "modality-not-str",
            "negative",
            "bool",
            "string-count",
            "float-count",
            "null-count",
        ],
    )
    def test_one_malformed_entry_makes_the_whole_field_unknown(self, entry: Any) -> None:
        # INVARIANT: never a partial sum — a sum that skipped an entry is a false known value.
        usage = {"promptTokensDetails": [{"modality": "IMAGE", "tokenCount": 100}, entry]}
        assert image_and_file_tokens_from_gemini(usage) is None

    def test_sum_beyond_the_count_bound_is_unknown(self) -> None:
        usage = {
            "promptTokensDetails": [
                {"modality": "IMAGE", "tokenCount": 2**53 - 1},
                {"modality": "DOCUMENT", "tokenCount": 1},
            ]
        }
        assert image_and_file_tokens_from_gemini(usage) is None

    def test_not_a_mapping_is_unknown(self) -> None:
        assert image_and_file_tokens_from_gemini(None) is None
        assert image_and_file_tokens_from_gemini([]) is None


def test_key_name_is_the_documented_one() -> None:
    assert IMAGE_AND_FILE_KEY == "image_and_file_tokens"
