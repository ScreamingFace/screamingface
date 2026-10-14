"""Pure DRACO rubric scoring primitives.

These formulas mirror ``screamingface-benchmarks/benchmarking/graders/rubric.py``
(arXiv:2602.11685 §4.2). They are deliberately isolated from execution framing and
aggregation so protocol math can be reviewed and tested without the URL4 payload
machinery.

INVARIANT: changes that make these formulas more intuitive but diverge from the pinned reference
create a different benchmark and must not land as DRACO.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from statistics import stdev
from typing import Any


def flatten_criteria(rubric: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Walk rubric sections into criteria with their scoring axis attached."""
    for section in rubric.get("sections", []):
        axis = section.get("id") or section.get("title") or "unknown"
        for criterion in section.get("criteria") or []:
            row = dict(criterion)
            row.setdefault("weight", 0)
            row["axis"] = axis
            yield row


def normalized_score(rubric: Mapping[str, Any], verdicts: Mapping[str, bool]) -> float:
    """Weight-aware score in [0, 1] — ``clamp(Σ MET·w / Σ w⁺)``."""
    weighted_sum = 0.0
    denom_pos = 0.0
    for criterion in flatten_criteria(rubric):
        weight = float(criterion.get("weight", 0))
        met = bool(verdicts.get(criterion["id"], False))
        if weight > 0:
            denom_pos += weight
            if met:
                weighted_sum += weight
        elif weight < 0 and met:
            weighted_sum += weight
    if denom_pos <= 0:
        return 0.0
    return max(0.0, min(1.0, weighted_sum / denom_pos))


def pass_rate(rubric: Mapping[str, Any], verdicts: Mapping[str, bool]) -> float:
    """Unweighted fraction of positive criteria met and negative criteria avoided."""
    n_correct = 0
    n_total = 0
    for criterion in flatten_criteria(rubric):
        weight = float(criterion.get("weight", 0))
        met = bool(verdicts.get(criterion["id"], False))
        if (weight >= 0 and met) or (weight < 0 and not met):
            n_correct += 1
        n_total += 1
    return (n_correct / n_total) if n_total else 0.0


def axis_scores(rubric: Mapping[str, Any], verdicts: Mapping[str, bool]) -> dict[str, float]:
    """Recompute :func:`normalized_score` independently for each rubric section."""
    by_axis: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for criterion in flatten_criteria(rubric):
        weight = float(criterion.get("weight", 0))
        met = bool(verdicts.get(criterion["id"], False))
        achieved, achievable = by_axis[criterion["axis"]]
        if weight >= 0:
            achievable += weight
            if met:
                achieved += weight
        elif met:
            achieved += weight
        by_axis[criterion["axis"]] = [achieved, achievable]
    return {
        axis: (max(0.0, min(1.0, achieved / achievable)) if achievable > 0 else 0.0)
        for axis, (achieved, achievable) in by_axis.items()
    }


def axis_pass_rates(rubric: Mapping[str, Any], verdicts: Mapping[str, bool]) -> dict[str, float]:
    """Recompute the unweighted :func:`pass_rate` independently for each axis."""

    by_axis: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for criterion in flatten_criteria(rubric):
        weight = float(criterion.get("weight", 0))
        met = bool(verdicts.get(criterion["id"], False))
        correct, total = by_axis[criterion["axis"]]
        if (weight >= 0 and met) or (weight < 0 and not met):
            correct += 1
        by_axis[criterion["axis"]] = [correct, total + 1]
    return {axis: (correct / total) if total else 0.0 for axis, (correct, total) in by_axis.items()}


def _factual_axis_value(axes: Mapping[str, float]) -> float | None:
    """The Factual Accuracy axis value, or ``None`` when this rubric has no such axis.

    INVARIANT: absence is NOT zero. A rubric without a Factual Accuracy section would otherwise
    publish ``accuracy: 0.0`` for a Candidate that scored 1.0, which reads as "0% factually
    accurate" — the same absence-renders-as-zero error this module refuses for ``score``.
    """
    for axis, value in axes.items():
        normalized = str(axis).lower().replace("_", "-").replace(" ", "-")
        if normalized in {"factual-accuracy", "factualaccuracy"}:
            return float(value)
    return None


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _restrict(rubric: Mapping[str, Any], judged_ids: Sequence[str]) -> dict[str, Any]:
    """Remove unjudged criteria from both the scoring numerator and denominator."""
    keep = set(judged_ids)
    return {
        "sections": [
            {
                **section,
                "criteria": [c for c in (section.get("criteria") or []) if c.get("id") in keep],
            }
            for section in rubric.get("sections", [])
        ]
    }


def score_case(
    rubric: Mapping[str, Any],
    runs: Sequence[Mapping[str, bool]],
    *,
    criteria_expected: int | None = None,
) -> dict[str, Any]:
    """Score each judge pass independently, then report its mean and sample spread."""
    total = (
        criteria_expected
        if criteria_expected is not None
        else sum(1 for _ in flatten_criteria(rubric))
    )
    scored = [_score_one_run(rubric, verdicts, total) for verdicts in runs]
    if not scored:
        return {
            "normalized_score": 0.0,
            "normalized_score_sd": 0.0,
            "pass_rate": 0.0,
            "pass_rate_sd": 0.0,
            # No run was scored, so no axis was observed — unknown, not zero.
            "accuracy": None,
            "accuracy_pass_rate": None,
            "axis_scores": {},
            "axis_pass_rates": {},
            "coverage": 0.0,
            "coverage_sd": 0.0,
            "n_runs": 0,
        }
    axes: dict[str, list[float]] = defaultdict(list)
    axis_passes: dict[str, list[float]] = defaultdict(list)
    for run in scored:
        for axis, value in run["axis_scores"].items():
            axes[axis].append(value)
        for axis, value in run["axis_pass_rates"].items():
            axis_passes[axis].append(value)
    norms = [run["normalized_score"] for run in scored]
    pass_rates = [run["pass_rate"] for run in scored]
    coverages = [run["coverage"] for run in scored]
    axis_means = {axis: round(_avg(values), 4) for axis, values in axes.items()}
    axis_pass_means = {axis: round(_avg(values), 4) for axis, values in axis_passes.items()}
    return {
        "normalized_score": round(_avg(norms), 4),
        "normalized_score_sd": round(_stdev(norms), 4),
        "pass_rate": round(_avg(pass_rates), 4),
        "pass_rate_sd": round(_stdev(pass_rates), 4),
        "accuracy": _round_optional(_factual_axis_value(axis_means)),
        "accuracy_pass_rate": _round_optional(_factual_axis_value(axis_pass_means)),
        "axis_scores": axis_means,
        "axis_pass_rates": axis_pass_means,
        "coverage": round(_avg(coverages), 4),
        "coverage_sd": round(_stdev(coverages), 4),
        "n_runs": len(scored),
    }


def _score_one_run(
    rubric: Mapping[str, Any], verdicts: Mapping[str, bool], total: int
) -> dict[str, Any]:
    restricted = _restrict(rubric, list(verdicts))
    return {
        "normalized_score": normalized_score(restricted, verdicts),
        "pass_rate": pass_rate(restricted, verdicts),
        "axis_scores": axis_scores(restricted, verdicts),
        "axis_pass_rates": axis_pass_rates(restricted, verdicts),
        "coverage": (len(verdicts) / total) if total else 0.0,
    }


def _avg(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return stdev(values)
