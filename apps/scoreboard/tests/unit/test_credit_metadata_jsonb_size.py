"""The metadata byte cap must survive PostgreSQL's integral JSONB number decoding."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from scoreboard.scores.credit_metadata import METADATA_MAX_BYTES, stored_size
from scoreboard.scores.schemas import ScoreMetadataPatch, ScoreSubmission


@pytest.mark.parametrize("value", [1e23, 1.5e300, 1e308, -1.5e300, 1.0])
def test_size_accounts_for_both_integral_number_spellings(value: float) -> None:
    expanded = int(Decimal(repr(value)))
    expected = max(
        len(json.dumps({"number": number}, separators=(",", ":"))) for number in (value, expanded)
    )

    assert stored_size({"number": value}) == expected


@pytest.mark.parametrize("schema", [ScoreSubmission, ScoreMetadataPatch])
def test_numbers_cannot_expand_past_the_cap_after_storage(schema: type) -> None:
    authors = [f"a{i}@example.test" for i in range(10)]
    metadata = {author: {f"{i:02d}" + "k" * 62: 1.5e300 for i in range(20)} for author in authors}
    # The ordinary encoder sees only 15,401 bytes; JSONB returns 74,001 bytes of integers.
    assert len(json.dumps(metadata, separators=(",", ":"))) < METADATA_MAX_BYTES
    payload = {"authors": authors, "authors_metadata": metadata}
    if schema is ScoreSubmission:
        payload.update(
            benchmark_id="hle",
            spec_id="numeric-size",
            url4_expression="url4://numeric-size",
            score=0.75,
            total_questions=4,
            ran_with_providers=["openai"],
        )

    with pytest.raises(ValidationError) as caught:
        schema.model_validate(payload)

    assert [error["loc"] for error in caught.value.errors()] == [("authors_metadata",)]


def test_fractional_numbers_keep_their_encoding() -> None:
    values = {"fraction": 1.5, "tiny": 1e-100, "flag": True, "text": "1e300"}

    assert stored_size(values) == len(json.dumps(values, separators=(",", ":")))


def test_integral_float_scale_does_not_offset_exponent_expansion() -> None:
    values = {"exponent": 1e23, "decimal": 1.0}
    decoded = {"exponent": 10**23, "decimal": 1.0}

    assert stored_size(values) == len(json.dumps(decoded, separators=(",", ":")))
