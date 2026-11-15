"""Validate evidence-backed operator reviews before an observation can rank."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
)

from .comparison_profiles import PROFILES, ComparisonProfile
from .schemas import BaselineImportRow

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ComparisonEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: HttpUrl
    grading: HttpUrl
    coverage: HttpUrl
    units: HttpUrl


class ComparisonReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: Literal["1"]
    benchmark_revision: Text
    question_set_sha256: Text
    grading_id: Text
    evaluated_case_count: Annotated[int, Field(strict=True, gt=0)]
    original_score: Number
    original_unit: Text
    conversion: Literal[
        "identity", "percent_to_fraction", "fraction_to_percent", "count_to_fraction"
    ]
    reviewed_at: AwareDatetime
    prompt_note: Text
    evidence: ComparisonEvidence


def _profile(
    row: BaselineImportRow, revision: str | None, case_count: int | None
) -> ComparisonProfile:
    profile = PROFILES.get(row.benchmark_id)
    if profile is None or (revision, case_count) != (profile.revision, profile.case_count):
        raise ValueError("comparison requires a reviewed profile matching the current board scope")
    return profile


def _validate_scope(
    review: ComparisonReview, row: BaselineImportRow, profile: ComparisonProfile
) -> None:
    source = (
        review.benchmark_revision,
        review.question_set_sha256,
        review.grading_id,
        review.evaluated_case_count,
        row.metric_name,
    )
    target = (
        profile.revision,
        profile.question_set_sha256,
        profile.grading_id,
        profile.case_count,
        profile.metric_name,
    )
    if source != target:
        raise ValueError("comparison questions, grading, coverage or metric do not match the board")
    if row.metadata and row.metadata.get("strictly_comparable") is False:
        raise ValueError("observation explicitly records incompatible evaluation rules")


def _validate_provenance(review: ComparisonReview, row: BaselineImportRow) -> None:
    if not row.attached_by or row.observed_at is None or row.source_url is None:
        raise ValueError(
            "a reviewed result needs internal attribution, source URL and observation date"
        )
    TypeAdapter(HttpUrl).validate_python(row.source_url)
    if not row.observed_at <= review.reviewed_at <= datetime.now(UTC):
        raise ValueError("review date must follow observation and cannot be in the future")


def _convert(review: ComparisonReview, profile: ComparisonProfile) -> Decimal:
    original = Decimal(str(review.original_score))
    pair = (review.original_unit, profile.unit)
    if review.conversion == "identity":
        if pair[0] != pair[1]:
            raise ValueError("identity conversion requires identical units")
        return original
    return _convert_units(review, profile, original, pair)


def _convert_units(
    review: ComparisonReview,
    profile: ComparisonProfile,
    original: Decimal,
    pair: tuple[str, str],
) -> Decimal:
    conversions = {
        "percent_to_fraction": (("percent", "fraction"), Decimal("0.01"), Decimal(100)),
        "fraction_to_percent": (("fraction", "percent"), Decimal(100), Decimal(1)),
    }
    if review.conversion in conversions:
        expected, factor, maximum = conversions[review.conversion]
        if pair != expected or not 0 <= original <= maximum:
            raise ValueError("source units or value do not support the declared conversion")
        return original * factor
    if (
        pair != ("correct_count", "fraction")
        or profile.metric_name != "accuracy"
        or original != original.to_integral_value()
        or not 0 <= original <= profile.case_count
    ):
        raise ValueError(
            "count conversion requires an integer correct count over the full accuracy test"
        )
    return original / Decimal(profile.case_count)


def validate_comparison(
    row: BaselineImportRow,
    *,
    revision: str | None,
    case_count: int | None,
) -> bool:
    # INVARIANT: storing an observation is not approval. Legacy and unreviewed
    # imports remain usable as records, but never acquire eligibility by default.
    if not row.metadata or "comparison" not in row.metadata:
        return False
    review = ComparisonReview.model_validate(row.metadata["comparison"])
    profile = _profile(row, revision, case_count)
    _validate_scope(review, row, profile)
    _validate_provenance(review, row)
    converted = _convert(review, profile)
    if not profile.minimum <= converted <= profile.maximum or row.score != float(converted):
        raise ValueError("score does not equal the documented conversion in the board's range")
    return True
