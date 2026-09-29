"""Install one DRACO benchmark's private assets and functions into a Runner world.

The benchmark's routes and judge-pass count come from the :class:`DracoVariant` the benchmark
module passes in — the same dataset assets serve every benchmark, and only the
addresses and the evidence cardinality differ.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.draco import assets as protocol_assets
from screamingface_engine.benchmarks.draco import grade as grading
from screamingface_engine.benchmarks.draco import judge_requests, records
from screamingface_engine.benchmarks.draco import scoring as rubric_scoring
from screamingface_engine.benchmarks.draco.case_grade import (
    build_case_grade,
    build_criterion_grade,
)
from screamingface_engine.benchmarks.draco.check_policy import DRACO_DRAFT_FEEDBACK
from screamingface_engine.benchmarks.draco.prompts import judge_context, judge_intent
from screamingface_engine.benchmarks.draco.variant import (
    CASE_COUNT,
    JUDGE_MODEL,
    JUDGE_PARAMS,
    DracoVariant,
)
from screamingface_engine.benchmarks.draco.verdict import build_evidence_record, evidence_record_key
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_definition_error as _definition_error,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    aggregate_endpoint,
    candidate_answer,
    case_grade_endpoint,
    compact_json,
    json_object,
)
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.rubric_draft_feedback import rubric_draft_feedback_endpoint
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    register_grading_request,
)
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path, variant: DracoVariant) -> None:
    """Register the routes referenced by one DRACO benchmark.

    INVARIANT (OME-999): install registers LAZY providers and reads no asset. A Runner world
    carries every registered benchmark, so an eager read here would make every other benchmark's run
    require DRACO's assets — the shared lazy-install contract HealthBench's install documents.
    Assets load on the first resolution of one of THIS benchmark's routes; only successes are
    memoized, so a missing asset fails identically — and loudly — on every resolution.
    """
    assets = _lazy_protocol_assets(root)
    install_cases(node, variant.routes.cases, _cases(assets))
    node.endpoint(variant.routes.judge_requests)(_judge_request_rows(root, variant))
    # The mid-run draft-feedback offer the corrective loop consumes. It closes over `node` so the
    # judge route resolves per request — installation must still work in a world that holds
    # no model routes at all (every benchmark-only test builds one).
    node.endpoint(variant.routes.check_surface)(
        rubric_draft_feedback_endpoint(
            node,
            root,
            DRACO_DRAFT_FEEDBACK,
        )
    )
    node.endpoint(variant.routes.verdict)(_criterion_verdict(variant.id))
    node.endpoint(variant.routes.criterion_evaluation)(_criterion_evaluation(variant.judge_passes))
    node.endpoint(variant.routes.case_evaluation)(
        case_grade_endpoint(
            label="DRACO Case evaluation",
            item_name="Criterion evaluation",
            bind=build_case_grade,
        )
    )
    node.endpoint(variant.routes.aggregate)(
        aggregate_endpoint(
            label="DRACO",
            # WHY the constant: the lazy load validates len(cases) == CASE_COUNT on first
            # resolution, so the eager `len(selected_cases)` this replaced was always equal.
            available_case_count=CASE_COUNT,
            aggregate=_aggregate(
                assets,
                variant,
            ),
        )
    )


ProtocolAssets = tuple[str, list[dict[str, object]], dict[int, dict[str, Any]]]


def _lazy_protocol_assets(root: Path) -> Callable[[], ProtocolAssets]:
    """A memoized accessor for the shared assets — loaded on first use, never at install.

    Prepared assets are immutable for the process lifetime, so one successful load serves every
    later resolution. A FAILED load is never cached: the next resolution re-reads and re-fails
    with the same named error, keeping missing-asset failures loud rather than one-shot.
    """

    memo: dict[str, ProtocolAssets] = {}

    def load() -> ProtocolAssets:
        if "assets" not in memo:
            memo["assets"] = _protocol_assets(root)
        return memo["assets"]

    return load


def _cases(assets: Callable[[], ProtocolAssets]):
    @observe_phase(ActivityKind.CASE_LOADING)
    def cases() -> str:
        return assets()[0]

    return cases


def _protocol_assets(
    root: Path,
) -> ProtocolAssets:
    """Load and validate DRACO's shared assets before serving any route."""

    raw = _read(root / "cases.json", "DRACO cases")
    selected = _parse_cases(raw)
    if len(selected) != CASE_COUNT:
        raise _definition_error(f"expected {CASE_COUNT} DRACO cases, got {len(selected)}")
    try:
        rubrics = protocol_assets.validate_protocol_assets(root, selected)
    except (OSError, ValueError) as exc:
        # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
        # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
        raise _unavailable(str(exc)) from exc
    return (
        json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
        selected,
        rubrics,
    )


def _judge_request_rows(
    root: Path,
    variant: DracoVariant,
):
    @observe_phase(ActivityKind.GRADING)
    def judge_request_rows(request: Request) -> str:
        try:
            case_id = judge_requests.positive_case_id(request.intent)
            report_case_grading(case_id, "started")
            answer = candidate_answer(request.context)
            evaluator_text = answer.text
            raw_cases = _read(root / "cases.json", "DRACO cases")
            criteria = judge_requests.load_criteria(root / "criteria", case_id)
            rubric = json_object(
                _read(root / "rubrics" / f"{case_id}.json", f"DRACO Case {case_id} rubric"),
                f"DRACO Case {case_id} rubric",
            )
            selected = list(rubric_scoring.flatten_criteria(rubric))
            criteria_by_id = {str(criterion.get("id")): criterion for criterion in criteria}
            selected_criteria = [criteria_by_id[str(criterion["id"])] for criterion in selected]
            result = judge_requests.build_judge_requests(
                case_id,
                judge_requests.load_question(root / "criteria", case_id),
                evaluator_text,
                selected_criteria,
            )
            case_record = records.bind_case(
                raw_cases,
                case_id=case_id,
                candidate=answer,
            )
            for index, row in enumerate(result):
                request_context = judge_context(
                    criterion_type=row["criterion_type"],
                    criterion=row["criterion"],
                    question=row["question"],
                    answer=row["answer"],
                )
                request_intent = judge_intent()
                for sequence in range(1, variant.judge_passes + 1):
                    register_grading_request(
                        GradingEvidenceOwner(
                            benchmark_id=variant.id,
                            case_id=case_id,
                            check_id=row["criterion_id"],
                            sequence=sequence,
                        ),
                        path="/" + JUDGE_MODEL.removeprefix("/"),
                        params={**dict(JUDGE_PARAMS), "seed": str(sequence)},
                        context=request_context,
                        intent=request_intent,
                    )
                row["case_record"] = (
                    json.dumps(case_record, ensure_ascii=False, separators=(",", ":"))
                    if index == 0
                    else "{}"
                )
                row["check_record"] = json.dumps(
                    records.bind_check(
                        row["criterion"],
                        case_id=case_id,
                        criterion_id=row["criterion_id"],
                        criterion_type=row["criterion_type"],
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        except (OSError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
            # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
            raise _unavailable(str(exc)) from exc
        return compact_json(result)

    return judge_request_rows


def _criterion_verdict(benchmark_id: str):
    @observe_phase(ActivityKind.GRADING)
    def criterion_verdict(request: Request) -> str:
        try:
            case_id, sequence, criterion_id = evidence_record_key(request.intent)
            record = build_evidence_record(
                request.context,
                case_id=case_id,
                criterion_id=criterion_id,
                sequence=sequence,
                producer_id=JUDGE_MODEL,
            )
        except ValueError as exc:
            raise _contract_error(str(exc)) from exc
        accounting = accounting_for_grading_evidence(
            GradingEvidenceOwner(
                benchmark_id=benchmark_id,
                case_id=case_id,
                check_id=criterion_id,
                sequence=sequence,
            )
        )
        record["accounting"] = accounting.model_dump() if accounting is not None else None
        return compact_json(record)

    return criterion_verdict


def _criterion_evaluation(judge_passes: int):
    """One criterion-evaluation handler bound to its benchmark's judge-pass count.

    The protocol posts exactly ``judge_passes`` evidence records per criterion, so the
    handler demands exactly those field names — a five-pass expression cannot resolve
    against a three-pass benchmark's route and vice versa (every route is revision-pinned).
    """

    @observe_phase(ActivityKind.GRADING)
    def handle(request: Request) -> str:
        try:
            case_id = judge_requests.positive_case_id(request.intent)
            payload = json_object(request.context, "DRACO Criterion evaluation")
            expected = (
                "case",
                "check",
                *(f"evidence_{sequence}" for sequence in range(1, judge_passes + 1)),
            )
            if tuple(payload) != expected:
                raise ValueError(
                    "DRACO Criterion evaluation fields must be case, check, and consecutive "
                    "evidence_1..evidence_N"
                )
            raw_case = json_object(payload["case"], "Case record")
            case_record = raw_case or None
            check_record = json_object(payload["check"], "Check record")
            evidence = [
                json_object(payload[field], field)
                for field in expected
                if field.startswith("evidence_")
            ]
            result = build_criterion_grade(
                case_id,
                case_record,
                check_record,
                evidence,
            )
        except (TypeError, ValueError) as exc:
            raise _contract_error(str(exc)) from exc
        return compact_json(result)

    return handle


def _aggregate(
    assets: Callable[[], ProtocolAssets],
    variant: DracoVariant,
):
    def aggregate(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        _cases_json, selected_cases, rubrics = assets()
        return grading.aggregate(
            case_evaluations,
            rubrics,
            variant.id,
            selected_cases=selected_cases[:selected_case_count],
            judge_passes=variant.judge_passes,
            benchmark_revision=variant.revision,
        )

    return aggregate


def _parse_cases(raw: str) -> list[dict[str, object]]:
    try:
        cases = json.loads(raw)
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            raise ValueError("expected a JSON array of objects")
        return cases
    except (TypeError, ValueError) as exc:
        raise _unavailable(f"could not read DRACO cases: {exc}") from exc


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = ["install"]
