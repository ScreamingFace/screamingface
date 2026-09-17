"""Pure mapping from a completed Report to inspect's EvalLog document.

Think of this module as a translator with no phrasebook dependency: it turns one
Candidate's run into the plain-JSON document that inspect's own
``EvalLog.model_validate`` accepts, without importing ``inspect_ai`` at all. The
shapes were verified live against the pinned ``inspect-ai==0.3.263``
(OME-1117 spec §1). The writer module hands this payload to inspect's writer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, Report

# WHY a closed translation table: inspect's ChatCompletionChoice.stop_reason is a
# closed literal set, while our finish_reason is provider-verbatim text. Anything
# we cannot translate faithfully becomes "unknown" rather than a guess.
_STOP_REASONS: dict[str, str] = {
    "stop": "stop",
    "length": "max_tokens",
    "max_tokens": "max_tokens",
    "content_filter": "content_filter",
    "tool_calls": "tool_calls",
}

# The one scorer name the exported log speaks under — also the sample score key.
_SCORER = "screamingface"

# inspect's EvalLog schema version at the pinned inspect-ai 0.3.263.
_LOG_VERSION = 2


def eval_log_payload(report: Report, candidate: str | None = None) -> dict[str, Any]:
    """Project one Candidate's run into inspect's EvalLog document shape.

    Stages, in the order the document is assembled:

    1. Select the Candidate — a single-candidate Report needs no selector; a
       multi-candidate Report must name one, because an inspect log is one
       task × one model by their own convention.
    2. Build the spec block — benchmark id as the task, the Report's SELECTED
       case count as the dataset size (a limited run stays recognisably
       partial), and the provenance metadata that stamps the log as OUR
       one-way export (never a leaderboard source).
    3. Map each Case to a sample — input (decoded chat turns or raw text),
       the Candidate's answer as the model output, the grade as a score, and
       our failure vocabulary riding along in sample metadata.
    4. Summarize — score/coverage metrics, run window, and the metered cost
       passed through untouched (it IS the gateway meter).

    Args:
        report: the completed Report to export from.
        candidate: the Candidate name to export; required when the Report
            holds more than one Candidate.

    Returns:
        A JSON-serializable dict accepted by ``EvalLog.model_validate`` at the
        pinned inspect-ai version.
    """
    selected: CandidateResult = _select_candidate(report, candidate)
    return {
        "version": _LOG_VERSION,
        # WHY status mirrors our scored/failed split: an unscored Candidate is a
        # run that did not complete its purpose, which is inspect's "error".
        "status": "success" if selected.score is not None else "error",
        "eval": _spec_payload(report, selected),
        "results": _results_payload(selected),
        "stats": _stats_payload(selected),
        "samples": [_sample_payload(case, selected) for case in selected.cases],
    }


def _select_candidate(report: Report, candidate: str | None) -> CandidateResult:
    """Resolve which Candidate one log describes; refuse ambiguity loudly."""
    names: list[str] = [value.name for value in report.candidates]
    if candidate is None:
        if len(names) > 1:
            listed = ", ".join(repr(name) for name in names)
            raise ValueError(
                f"this Report holds {len(names)} Candidates ({listed}); an inspect log "
                "is one Candidate's run — pass candidate=<name> to select one"
            )
        return report.candidates[0]
    for value in report.candidates:
        if value.name == candidate:
            return value
    raise ValueError(f"unknown Candidate {candidate!r}; this Report holds: {names}")


def _spec_payload(report: Report, selected: CandidateResult) -> dict[str, Any]:
    """The EvalSpec block: task identity plus our provenance stamp."""
    from screamingface.report import _timestamp_text

    return {
        "created": _timestamp_text(selected.started_at),
        "task": report.benchmark.id,
        # INVARIANT: the SELECTED Evaluation size, not the full Benchmark size —
        # same convention as the Report root (report.py to_dict INVARIANT).
        "dataset": {"name": report.benchmark.id, "samples": report.case_count},
        "model": selected.name,
        "config": {},
        "tags": ["screamingface-export"],
        # INVARIANT (one-way export): the log names US as the producer and never
        # carries an expression_sha, so the leaderboard path cannot ingest it.
        "metadata": {
            "produced_by": "ScreamingFace engine",
            "source_schema": "screamingface.report.v1",
            "one_way_export": True,
            "benchmark_revision": report.benchmark.revision,
            "run_id": selected.run_id,
            "recipe_kind": selected.kind,
            "recipe_url4": str(selected.url4),
            "answer_seed": selected.answer_seed,
            "cost_usd": (None if selected.usage.cost_usd is None else str(selected.usage.cost_usd)),
            "member_usage": _member_usage(selected),
        },
    }


def _sample_payload(case: CaseResult, selected: CandidateResult) -> dict[str, Any]:
    """One Case as one inspect sample; our vocabulary rides in metadata."""
    turns = case.conversation
    sample: dict[str, Any] = {
        "id": case.case_id,
        "epoch": 1,
        "input": (
            case.input
            if turns is None
            else [{"role": role, "content": content} for role, content in turns]
        ),
        # WHY empty target: the client never holds gold answers — grading already
        # happened engine-side, so the sample's truth lives in its score.
        "target": "",
        "metadata": _sample_metadata(case),
    }
    if case.output is not None:
        sample["output"] = _output_payload(case, selected)
    if case.grade is not None and case.grade.score is not None:
        sample["scores"] = {
            _SCORER: _score_payload(case),
        }
    return sample


def _output_payload(case: CaseResult, selected: CandidateResult) -> dict[str, Any]:
    """The Candidate's answer as an inspect ModelOutput document."""
    stop_reason: str = _STOP_REASONS.get(case.finish_reason or "", "unknown")
    return {
        "model": selected.name,
        "choices": [
            {
                "message": {"role": "assistant", "content": case.output},
                "stop_reason": stop_reason,
            }
        ],
    }


def _score_payload(case: CaseResult) -> dict[str, Any]:
    """The engine-side grade as an inspect Score document."""
    grade = case.grade
    assert grade is not None  # guarded by the caller
    # WHY the refusal fallback: a graded refusal is a scored Case whose answer IS
    # the refusal text (OME-1037) — output and refusal are mutually exclusive there.
    score: dict[str, Any] = {
        "value": grade.score,
        "answer": case.output if case.output is not None else case.refusal,
    }
    explanation: str | None = _first_explanation(case)
    if explanation is not None:
        score["explanation"] = explanation
    return score


def _first_explanation(case: CaseResult) -> str | None:
    """The first valid grading explanation, in the checks' own order."""
    if case.grade is None:
        return None
    for check in case.grade.checks:
        for evidence in check.evidence:
            if evidence.valid and evidence.explanation is not None:
                return evidence.explanation
    return None


def _sample_metadata(case: CaseResult) -> dict[str, Any]:
    """Our per-Case vocabulary, carried verbatim for their analysis scripts."""
    metadata: dict[str, Any] = {"status": case.status}
    if case.refusal is not None:
        metadata["refusal"] = case.refusal
    if case.finish_reason is not None:
        metadata["finish_reason"] = case.finish_reason
    if case.stop_reason is not None:
        metadata["stop_reason"] = case.stop_reason
    if case.rounds_executed is not None:
        metadata["rounds_executed"] = case.rounds_executed
    if case.failures:
        metadata["failures"] = [failure.to_dict() for failure in case.failures]
    return metadata


def _results_payload(selected: CandidateResult) -> dict[str, Any]:
    """Candidate-level score and coverage as the log's headline metrics."""
    completed: int = sum(
        1 for case in selected.cases if case.grade is not None and case.grade.score is not None
    )
    metrics: dict[str, Any] = {}
    if selected.score is not None:
        metrics["score"] = {"name": "score", "value": selected.score}
    metrics["coverage"] = {"name": "coverage", "value": selected.coverage}
    return {
        "total_samples": len(selected.cases),
        "completed_samples": completed,
        "scores": [{"name": _SCORER, "scorer": _SCORER, "metrics": metrics}],
    }


def _stats_payload(selected: CandidateResult) -> dict[str, Any]:
    """Run window plus token/cost usage — the metered cost passed through."""
    from screamingface.report import _timestamp_text

    # INVARIANT: the meter appears EXACTLY ONCE. inspect's viewer sums the
    # model_usage map, so adding per-member rows beside the aggregate would
    # display an inflated total (aggregate + members). The member breakdown is
    # provenance and rides eval.metadata instead (see _member_usage).
    return {
        "started_at": _timestamp_text(selected.started_at),
        "completed_at": _timestamp_text(selected.completed_at),
        "model_usage": {selected.name: _usage_payload(selected.usage)},
    }


def _member_usage(selected: CandidateResult) -> list[dict[str, Any]]:
    """Per-member usage breakdown for the provenance block — data, never summed."""
    return [
        {
            "name": member.name,
            # WHY the id rides along: display names are cosmetic and may repeat
            # (the same model via two providers); identity is the operation_id.
            "operation_id": member.operation_id,
            "usage": _usage_payload(member.usage),
        }
        for member in selected.members
        if member.usage is not None
    ]


def _usage_payload(usage: Any) -> dict[str, Any]:
    """One Usage as inspect's ModelUsage; absent numbers stay absent."""
    input_tokens: int = usage.input_tokens or 0
    output_tokens: int = usage.output_tokens or 0
    payload: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if usage.cache_read_tokens is not None:
        payload["input_tokens_cache_read"] = usage.cache_read_tokens
    if usage.cache_creation_tokens is not None:
        payload["input_tokens_cache_write"] = usage.cache_creation_tokens
    if usage.reasoning_tokens is not None:
        payload["reasoning_tokens"] = usage.reasoning_tokens
    # INVARIANT: the cost is the gateway meter passed through — an unpriced run
    # exports with NO total_cost rather than a fabricated zero.
    if usage.cost_usd is not None:
        payload["total_cost"] = float(usage.cost_usd)
    return payload
