"""IFEval's production early grading and typed-result aggregation."""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.aggregation import SelectedCase, finalize_candidate_result
from screamingface_engine.benchmarks.graded_results import decode_results, encode_result
from screamingface_engine.benchmarks.ifeval import grade
from screamingface_engine.benchmarks.ifeval.definition import BENCHMARK_ID, REVISION
from screamingface_engine.benchmarks.stages import observe_stage
from url4.core.errors import ResolutionError
from url4.peer.server import Request


class CaseFinalizationError(ResolutionError):
    """A corrupt grade remains a run-level failure after on_error=collect."""


def _failure(selected, index, errors):
    # INVARIANT: moving validation earlier must not turn a corrupt run into a partial score.
    if errors and errors[0]["error"].get("kind") == "CaseFinalizationError":
        raise grade.AggregateError("invalid completed IFEval Case result")
    return grade._missing_row_result(selected, index, errors)


def case_result(root: Path):
    @observe_stage(ActivityKind.GRADING)
    async def handler(request: Request) -> str:
        try:
            case_id = int(request.intent)
            if case_id < 1:
                raise ValueError("Case id must be positive")
            spec = json.loads((root / "instructions" / f"{case_id}.json").read_text())
            if not isinstance(spec, dict):
                raise ValueError("selected Case has no valid installed instruction spec")
            selected = SelectedCase(case_id=case_id, input=str(spec["prompt"]), metadata={})
            # WHY: grade once in execution; aggregation never depends on a log callback.
            results = [
                result
                async for result in grade.scored_path({case_id: spec}).iter_case_results(
                    json.dumps([request.context]),
                    selected_cases=[selected],
                    grading_material=lambda _: spec,
                )
            ]
            if len(results) != 1:
                raise ValueError("IFEval must produce one Case result")
            return encode_result(results[0], benchmark_id=BENCHMARK_ID, revision=REVISION)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CaseFinalizationError(
                str(exc), code="benchmark_contract_error", permanent=True
            ) from exc

    return handler


def aggregate(root: Path):
    def handler(raw: str, selected_case_count: int):
        specs = grade.load_specs(root / "instructions")
        selected = grade._selected_cases(specs, grade.load_case_order(root), selected_case_count)
        cases = decode_results(
            raw,
            benchmark_id=BENCHMARK_ID,
            revision=REVISION,
            selected=selected,
            failure=_failure,
        )
        return finalize_candidate_result(
            benchmark_id=BENCHMARK_ID,
            benchmark_revision=REVISION,
            selected_cases=selected,
            cases=cases,
            scorer=grade._ifeval_score,
        ).as_payload()

    return handler
