"""Install one DRACO board's private assets and functions into a Runner world.

The board's routes and judge-pass count come from the :class:`DracoExam` the board
module passes in — the same dataset assets serve every board, and only the
addresses and the evidence cardinality differ.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.draco import aggregate as scoring
from screamingface_engine.benchmarks.draco import assets as protocol_assets
from screamingface_engine.benchmarks.draco import records, tasks
from screamingface_engine.benchmarks.draco import scoring as rubric_scoring
from screamingface_engine.benchmarks.draco.case_evaluation import (
    bind_case_evaluation,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.check_policy import DRACO_CHECK
from screamingface_engine.benchmarks.draco.exam import (
    CASE_COUNT,
    JUDGE_MODEL,
    DracoExam,
)
from screamingface_engine.benchmarks.draco.verdict import bind, binding_key
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    candidate_answer,
    case_evaluation_endpoint,
    compact_json,
    json_object,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.rubric_check import check_surface
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path, exam: DracoExam) -> None:
    """Register the routes referenced by one DRACO board.

    INVARIANT (OME-999): install registers LAZY providers and reads no asset. A Runner world
    carries every registered board, so an eager read here would make every other board's run
    require DRACO's assets — the shared lazy-install contract HealthBench's install documents.
    Assets load on the first resolution of one of THIS board's routes; only successes are
    memoized, so a missing asset fails identically — and loudly — on every resolution.
    """
    assets = _lazy_protocol_assets(root)
    node.data(exam.routes.cases, _cases(assets), media_type="application/json")
    node.endpoint(exam.routes.tasks)(_task_rows(root))
    # The mid-run check surface the corrective loop consumes. It closes over `node` so the
    # judge route resolves per request — installation must still work in a world that holds
    # no model routes at all (every benchmark-only test builds one).
    node.endpoint(exam.routes.check_surface)(
        check_surface(
            node,
            root,
            DRACO_CHECK,
        )
    )
    node.endpoint(exam.routes.verdict)(_criterion_verdict)
    node.endpoint(exam.routes.criterion_evaluation)(_criterion_evaluation(exam.judge_passes))
    node.endpoint(exam.routes.case_evaluation)(
        case_evaluation_endpoint(
            label="DRACO Case evaluation",
            item_name="Criterion evaluation",
            bind=bind_case_evaluation,
        )
    )
    node.endpoint(exam.routes.aggregate)(
        aggregate_endpoint(
            label="DRACO",
            # WHY the constant: the lazy load validates len(cases) == CASE_COUNT on first
            # resolution, so the eager `len(selected_cases)` this replaced was always equal.
            available_case_count=CASE_COUNT,
            aggregate=_aggregate(
                assets,
                exam,
            ),
        )
    )


ProtocolAssets = tuple[str, list[dict[str, object]], dict[int, dict[str, Any]]]


def _lazy_protocol_assets(root: Path) -> Callable[[], ProtocolAssets]:
    """A memoized accessor for the board's shared assets — loaded on first use, never at install.

    Baked assets are immutable for the process lifetime, so one successful load serves every
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
        raise _unavailable(f"expected {CASE_COUNT} DRACO cases, got {len(selected)}")
    try:
        rubrics = protocol_assets.validate_protocol_assets(root, selected)
    except (OSError, ValueError) as exc:
        raise _unavailable(str(exc)) from exc
    return (
        json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
        selected,
        rubrics,
    )


def _task_rows(
    root: Path,
):
    def task_rows(request: Request) -> str:
        try:
            case_id = tasks.positive_case_id(request.intent)
            answer = candidate_answer(request.context)
            evaluator_text = answer.text
            raw_cases = _read(root / "cases.json", "DRACO cases")
            criteria = tasks.load_criteria(root / "criteria", case_id)
            rubric = json_object(
                _read(root / "rubrics" / f"{case_id}.json", f"DRACO Case {case_id} rubric"),
                f"DRACO Case {case_id} rubric",
            )
            selected = list(rubric_scoring.flatten_criteria(rubric))
            criteria_by_id = {str(criterion.get("id")): criterion for criterion in criteria}
            selected_criteria = [criteria_by_id[str(criterion["id"])] for criterion in selected]
            result = tasks.build_tasks(
                case_id,
                tasks.load_question(root / "criteria", case_id),
                evaluator_text,
                selected_criteria,
            )
            case_record = records.bind_case(
                raw_cases,
                case_id=case_id,
                candidate=answer,
            )
            for index, row in enumerate(result):
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
            raise _unavailable(str(exc)) from exc
        return compact_json(result)

    return task_rows


def _criterion_verdict(request: Request) -> str:
    try:
        case_id, sequence, criterion_id = binding_key(request.intent)
        record = bind(
            request.context,
            case_id=case_id,
            criterion_id=criterion_id,
            sequence=sequence,
            producer_id=JUDGE_MODEL,
        )
    except ValueError as exc:
        raise _unavailable(str(exc)) from exc
    return compact_json(record)


def _criterion_evaluation(judge_passes: int):
    """One criterion-evaluation handler bound to its board's judge-pass count.

    The protocol posts exactly ``judge_passes`` evidence records per criterion, so the
    handler demands exactly those field names — a five-pass expression cannot resolve
    against a three-pass board's route and vice versa (every route is revision-pinned).
    """

    def handle(request: Request) -> str:
        try:
            case_id = tasks.positive_case_id(request.intent)
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
            result = bind_criterion_evaluation(
                case_id,
                case_record,
                check_record,
                evidence,
            )
        except (TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        return compact_json(result)

    return handle


def _aggregate(
    assets: Callable[[], ProtocolAssets],
    exam: DracoExam,
):
    def aggregate(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        _cases_json, selected_cases, rubrics = assets()
        return scoring.aggregate(
            case_evaluations,
            rubrics,
            exam.id,
            selected_cases=selected_cases[:selected_case_count],
            judge_passes=exam.judge_passes,
            benchmark_revision=exam.revision,
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
