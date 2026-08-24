"""Install GDPval's private assets and deterministic functions into one Runner world.

If ``exam.py`` writes the recipe — the expression tree that names six routes — this module is
the kitchen: it registers a handler behind each route so the recipe can resolve. Data flows
through them in exam order:

    /cases             -> serve the selected work requests (from the baked assets)
    /rubric-tasks      -> Candidate submitted one Case: fetch its private rubric, render one
                          fully-built judge prompt per surviving criterion
    /rubric-verdict    -> parse one judge reply into a verdict (or raise -> retry)
    /rubric-evaluation -> staple {case, rubric, verdict} into one row
    /case-evaluation   -> collect a Case's criterion rows into its Case Evaluation
    /aggregate         -> reduce all Case artifacts into the final score

INVARIANT: everything here is deterministic. The model calls live in the expression, never in
these handlers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    candidate_answer,
    case_evaluation_endpoint,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.gdpval import aggregate as reducing
from screamingface_engine.benchmarks.gdpval import records
from screamingface_engine.benchmarks.gdpval.case_evaluation import (
    bind_case_evaluation,
    bind_rubric_evaluation,
)
from screamingface_engine.benchmarks.gdpval.check_policy import GDPVAL_CHECK
from screamingface_engine.benchmarks.gdpval.exam import Exam, ExamMean
from screamingface_engine.benchmarks.gdpval.pins import JUDGE_MODEL
from screamingface_engine.benchmarks.gdpval.prompts import build_grader_prompt, render_rubric_item
from screamingface_engine.benchmarks.gdpval.verdict import bind, binding_key
from screamingface_engine.benchmarks.rubric_check import check_surface
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path, exam: Exam) -> None:
    """Register every route this board's expressions reference.

    INVARIANT: routes are namespaced by board id AND revision, so several boards can install
    into ONE Runner world over ONE ``root`` without colliding.
    """

    if exam.routes.cases not in getattr(node, "_data", {}):
        node.data(exam.routes.cases, _cases(root, exam.case_ids), media_type="application/json")
    installed = frozenset(node.processor_routes())
    endpoints = (
        (exam.routes.tasks, _rubric_tasks(root, exam.case_ids)),
        # Closes over `node` so the judge route resolves per request — installation must still
        # work in a world holding no model routes.
        (exam.routes.check_surface, check_surface(node, root, GDPVAL_CHECK)),
        (exam.routes.verdict, _rubric_verdict),
        (exam.routes.rubric_evaluation, _rubric_evaluation),
        (
            exam.routes.case_evaluation,
            case_evaluation_endpoint(
                label="GDPval Case evaluation",
                item_name="Rubric evaluation",
                bind=bind_case_evaluation,
                error_context_head=300,
            ),
        ),
        (
            exam.routes.aggregate,
            aggregate_endpoint(
                label="GDPval",
                available_case_count=len(exam.case_ids),
                aggregate=_aggregate(root, exam.id, exam.revision, exam.case_ids, exam.mean),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam.

    A broken asset is knowable before any model runs. Without this check it would surface in the
    reducer — AFTER paying for a full Candidate run and ~44 judge calls per Case — only to score
    None. The reducer re-checks the same conditions: defence in depth.
    """

    problems: list[str] = []
    if not (root / "cases.json").is_file():
        problems.append(f"cases.json missing under {root}")
    else:
        try:
            cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
            present = {case.get("id") for case in cases if isinstance(case, Mapping)}
            missing = [case_id for case_id in case_ids if case_id not in present]
            if missing:
                problems.append(f"cases.json lacks selected cases {missing[:5]}")
        except (OSError, ValueError) as exc:
            problems.append(f"cases.json unreadable: {exc}")
    for case_id in case_ids:
        if reducing.load_rubric_points(root, case_id) is None:
            problems.append(f"rubric asset for case {case_id} missing or invalid")
    if problems:
        raise _unavailable("GDPval assets failed preflight: " + "; ".join(problems[:8]))


def _cases(root: Path, case_ids: tuple[int, ...]):
    def cases() -> str:
        preflight(root, case_ids)
        raw = _read(root / "cases.json", "GDPval cases")
        return json.dumps(_select_cases(raw, case_ids), ensure_ascii=False, separators=(",", ":"))

    return cases


def _rubric_tasks(root: Path, case_ids: tuple[int, ...]):
    """The fan-out point: one Candidate submission in, N ready-to-send judge tasks out."""

    def rubric_tasks(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            answer = candidate_answer(request.context)
            raw_cases = _read(root / "cases.json", "GDPval cases")
            work_request = _request_text(raw_cases, case_id)
            items = _rubric_items(root, case_id)
            case_record = records.bind_case(raw_cases, case_id=case_id, candidate=answer)
            tasks: list[dict[str, str]] = []
            for item in items:
                rendered = render_rubric_item(item["points"], item["criterion"])
                rubric_record = records.bind_rubric_item(
                    rendered, case_id=case_id, rubric_id=item["rubric_id"]
                )
                tasks.append(
                    {
                        "case_id": str(case_id),
                        "rubric_id": str(item["rubric_id"]),
                        # INVARIANT: the judge prompt is fully rendered HERE, Engine-side.
                        # Nothing about it is assembled inside the expression, so its bytes are
                        # fixed by the board's revision.
                        "grader_prompt": build_grader_prompt(work_request, answer.text, rendered),
                        # Dedup: the full Case record rides the FIRST task only; the rest carry
                        # "{}" and `case_evaluation` hoists it back to one record per Case.
                        "case_record": (
                            json.dumps(case_record, ensure_ascii=False, separators=(",", ":"))
                            if not tasks
                            else "{}"
                        ),
                        "rubric_record": json.dumps(
                            rubric_record, ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )
        except (OSError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        return compact_json(tasks)

    return rubric_tasks


def _rubric_verdict(request: Request) -> str:
    """The parse gate between "the judge said something" and "we have a verdict"."""

    try:
        case_id, rubric_id = binding_key(request.intent)
        record = bind(
            request.context, case_id=case_id, rubric_id=rubric_id, producer_id=JUDGE_MODEL
        )
    except ValueError as exc:
        raise _unavailable(str(exc)) from exc
    if record.get("valid") is not True:
        # WHY a transient error rather than a returned record: the expression's `;retry=` on this
        # route re-resolves the NESTED judge call, so each re-ask draws a fresh sample. After the
        # bounded retries the error propagates and the CASE fails loudly, keeping the reply head
        # as audit evidence.
        raw = str(record.get("raw_output") or "")
        raise ResolutionError(
            f"invalid judge reply for case {case_id} rubric {rubric_id} "
            f"({record.get('reason')}): {raw[:200]!r}",
            code="judge_reply_invalid",
            permanent=False,
        )
    return compact_json(record)


def _rubric_evaluation(request: Request) -> str:
    try:
        case_id = positive_case_id(request.intent)
        payload = json_object(request.context, "GDPval rubric evaluation")
        # Exact keys in exact order — the payload comes from OUR expression's struct(), so any
        # drift means the expression and the runtime disagree.
        if tuple(payload) != ("case", "rubric", "evidence"):
            raise ValueError("GDPval rubric evaluation fields must be case, rubric, evidence")
        raw_case = json_object(payload["case"], "Case record")
        result = bind_rubric_evaluation(
            case_id,
            raw_case or None,
            json_object(payload["rubric"], "Rubric record"),
            json_object(payload["evidence"], "Rubric verdict"),
        )
    except (TypeError, ValueError) as exc:
        raise _unavailable(str(exc)) from exc
    return compact_json(result)


def _aggregate(
    root: Path,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
    mean: ExamMean,
):
    def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        return reducing.aggregate(
            case_evaluations,
            root,
            benchmark_id=benchmark_id,
            benchmark_revision=benchmark_revision,
            case_ids=case_ids[:selected_case_count],
            mean=mean,
        )

    return aggregate_handler


def _request_text(raw_cases: str, case_id: int) -> str:
    """The work request the judge is shown, in exactly the bytes the Candidate received."""

    for row in json.loads(raw_cases):
        if isinstance(row, Mapping) and row.get("id") == case_id:
            envelope = json.loads(str(row.get("input")))
            if (
                not isinstance(envelope, Mapping)
                or envelope.get("schema") != CANDIDATE_INPUT_SCHEMA
            ):
                raise ValueError(f"GDPval case {case_id} input is not a candidate envelope")
            messages = envelope.get("messages")
            decoded = json.loads(messages) if isinstance(messages, str) else messages
            if not isinstance(decoded, list) or not decoded:
                raise ValueError(f"GDPval case {case_id} carries no messages")
            return "\n\n".join(
                str(turn.get("content", "")) for turn in decoded if isinstance(turn, Mapping)
            )
    raise ValueError(f"unknown GDPval case {case_id}")


def _rubric_items(root: Path, case_id: int) -> list[dict[str, Any]]:
    path = root / "rubrics" / f"{case_id}.json"
    decoded = json.loads(_read(path, f"GDPval rubric {case_id}"))
    items = decoded.get("items") if isinstance(decoded, Mapping) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"GDPval rubric {case_id} carries no items")
    return items


def _select_cases(raw: str, case_ids: tuple[int, ...]) -> list[dict[str, object]]:
    try:
        cases = json.loads(raw)
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            raise ValueError("expected a JSON array of objects")
        by_id = {case["id"]: case for case in cases}
        return [by_id[case_id] for case_id in case_ids]
    except (KeyError, TypeError, ValueError) as exc:
        raise _unavailable(f"could not select GDPval cases {case_ids}: {exc}") from exc


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = ["install", "preflight"]
