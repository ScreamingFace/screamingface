"""Reviewed board requirements; imported observations cannot redefine these."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ComparisonProfile:
    revision: str
    case_count: int
    question_set_sha256: str
    grading_id: str
    metric_name: str
    unit: str
    minimum: Decimal
    maximum: Decimal


# WHY: no generic "accuracy" default. The audit and pinned source references are in
# docs/external-result-comparison.md. New boards require an evidenced profile review.
PROFILES = {
    "inspect-agieval_sat_en": ComparisonProfile(
        revision="092ea478f523193d",
        case_count=206,
        question_set_sha256="33fe87b32ff16ae7ba52b27bb398190b082253b3617a3eb9737005262ba12dd4",
        grading_id="inspect-ai-0.3.263-choice",
        metric_name="accuracy",
        unit="fraction",
        minimum=Decimal(0),
        maximum=Decimal(1),
    ),
}
