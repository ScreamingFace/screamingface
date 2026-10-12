"""Install GDPval's private assets and deterministic functions into one Runner world.

If ``benchmark.py`` writes the recipe — the expression tree that names six routes — this module is
the kitchen: it registers a handler behind each route so the recipe can resolve. Data flows
through them in question order:

    /cases             -> serve the selected work requests (from the prepared assets)
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

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_definition_error as _definition_error,
)
from screamingface_engine.benchmarks.gdpval import grade as reducing
from screamingface_engine.benchmarks.gdpval import records
from screamingface_engine.benchmarks.gdpval.case_grade import (
    build_case_grade,
    build_rubric_grade,
)
from screamingface_engine.benchmarks.gdpval.check_policy import GDPVAL_DRAFT_FEEDBACK
from screamingface_engine.benchmarks.gdpval.prompts import build_grader_prompt, render_rubric_item
from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL, JUDGE_PARAMS
from screamingface_engine.benchmarks.gdpval.variant import GdpvalVariant, VariantMean
from screamingface_engine.benchmarks.gdpval.verdict import (
    build_evidence_record,
    evidence_record_key,
)
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.grading_endpoints import (
    candidate_answer,
    case_grade_endpoint,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.rubric_draft_feedback import rubric_draft_feedback_endpoint
from screamingface_engine.benchmarks.shared_grading.incremental_routes import (
    aggregate_result_endpoint,
    batch_result_endpoint,
    case_result_endpoint,
)
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    register_grading_request,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path, variant: GdpvalVariant) -> None:
    """Register every route this benchmark's expressions reference.

    INVARIANT: routes are namespaced by benchmark id AND revision, so several benchmarks can install
    into ONE Runner world over ONE ``root`` without colliding.
    """

    install_cases(node, variant.routes.cases, _cases(root, variant.case_ids))
    installed = frozenset(node.processor_routes())
    endpoints = (
        (
            variant.routes.aggregate + "/case-result",
            case_result_endpoint(
                _scoring(root, variant.id, variant.revision, variant.case_ids, variant.mean),
                available_case_count=len(variant.case_ids),
            ),
        ),
        (variant.routes.judge_requests, _rubric_judge_requests(root, variant.case_ids, variant.id)),
        # Closes over `node` so the judge route resolves per request — installation must still
        # work in a world holding no model routes.
        (
            variant.routes.check_surface,
            rubric_draft_feedback_endpoint(node, root, GDPVAL_DRAFT_FEEDBACK),
        ),
        (variant.routes.verdict, _rubric_verdict(variant.id)),
        (variant.routes.rubric_evaluation, _rubric_evaluation),
        (
            variant.routes.case_evaluation,
            case_grade_endpoint(
                label="GDPval Case evaluation",
                item_name="Rubric evaluation",
                bind=build_case_grade,
                error_context_head=300,
            ),
        ),
        (
            variant.routes.aggregate,
            batch_result_endpoint(
                label="GDPval",
                available_case_count=len(variant.case_ids),
                load=_scoring(root, variant.id, variant.revision, variant.case_ids, variant.mean),
            ),
        ),
        (
            variant.routes.aggregate + "/graded",
            aggregate_result_endpoint(
                label="GDPval",
                available_case_count=len(variant.case_ids),
                load=_scoring(root, variant.id, variant.revision, variant.case_ids, variant.mean),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def preflight(root: Path, case_ids: tuple[int, ...]) -> str:
    """Fail before the FIRST paid call when the prepared assets cannot serve this benchmark.

    A broken asset is knowable before any model runs. Without this check it would surface in the
    reducer — AFTER paying for a full Candidate run and ~44 judge calls per Case — only to score
    None. The reducer re-checks the same conditions: defence in depth.

    Returns the cases.json text it validated, so a caller that passes preflight never re-reads
    the multi-MB file it was just handed.
    """

    problems: list[str] = []
    raw = ""
    if not (root / "cases.json").is_file():
        problems.append(f"cases.json missing under {root}")
    else:
        try:
            raw = (root / "cases.json").read_text(encoding="utf-8")
            cases = json.loads(raw)
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
        raise _definition_error("GDPval assets failed preflight: " + "; ".join(problems[:8]))
    return raw


def _cases(root: Path, case_ids: tuple[int, ...]):
    # WHY a memo: prepared assets are immutable for the process lifetime, and cases.json is
    # multi-MB — it embeds the flattened text of all 85 reference documents. Only a SUCCESSFUL
    # payload is cached, so a broken asset re-checks (and re-fails loudly) on every call.
    memo: dict[str, str] = {}

    @observe_phase(ActivityKind.CASE_LOADING)
    def cases() -> str:
        if "payload" not in memo:
            raw = preflight(root, case_ids)
            memo["payload"] = json.dumps(
                _select_cases(raw, case_ids), ensure_ascii=False, separators=(",", ":")
            )
        return memo["payload"]

    return cases


def _rubric_judge_requests(root: Path, case_ids: tuple[int, ...], benchmark_id: str):
    """The fan-out point: one Candidate submission in, N ready-to-send judge requests out."""

    # WHY memos: without them a 102-case run re-reads and re-parses the multi-MB cases.json
    # ~204 times and re-opens every rubric file per submission. The prepared assets never change
    # within a process; failures are never cached, so a broken asset keeps failing visibly.
    raw_memo: dict[str, str] = {}
    text_memo: dict[int, str] = {}
    items_memo: dict[int, list[dict[str, Any]]] = {}

    @observe_phase(ActivityKind.GRADING)
    def rubric_judge_requests(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            report_case_grading(case_id, "started")
            answer = candidate_answer(request.context)
            if "cases" not in raw_memo:
                raw_memo["cases"] = _read(root / "cases.json", "GDPval cases")
            raw_cases = raw_memo["cases"]
            if case_id not in text_memo:
                text_memo[case_id] = _request_text(raw_cases, case_id)
            work_request = text_memo[case_id]
            if case_id not in items_memo:
                items_memo[case_id] = _rubric_items(root, case_id)
            case_record = records.case_record(raw_cases, case_id=case_id, candidate=answer)
            judge_requests: list[dict[str, str]] = []
            for item in items_memo[case_id]:
                rendered = render_rubric_item(item["points"], item["criterion"])
                grader_prompt = build_grader_prompt(work_request, answer.text, rendered)
                register_grading_request(
                    GradingEvidenceOwner(
                        benchmark_id=benchmark_id,
                        case_id=case_id,
                        check_id=str(item["rubric_id"]),
                        sequence=1,
                    ),
                    path="/" + JUDGE_MODEL.removeprefix("/"),
                    params=dict(JUDGE_PARAMS),
                    context=grader_prompt,
                    intent="",
                )
                rubric_record = records.rubric_item_record(
                    rendered, case_id=case_id, rubric_id=item["rubric_id"]
                )
                judge_requests.append(
                    {
                        "case_id": str(case_id),
                        "rubric_id": str(item["rubric_id"]),
                        # INVARIANT: the judge prompt is fully rendered HERE, Engine-side.
                        # Nothing about it is assembled inside the expression, so its bytes are
                        # fixed by the benchmark's revision.
                        "grader_prompt": grader_prompt,
                        # Dedup: the full Case record rides the FIRST task only; the rest carry
                        # "{}" and `case_evaluation` hoists it back to one record per Case.
                        "case_record": (
                            json.dumps(case_record, ensure_ascii=False, separators=(",", ":"))
                            if not judge_requests
                            else "{}"
                        ),
                        "rubric_record": json.dumps(
                            rubric_record, ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )
        except (OSError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
            # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
            raise _unavailable(str(exc)) from exc
        return compact_json(judge_requests)

    return rubric_judge_requests


def _rubric_verdict(benchmark_id: str):
    """The parse gate between "the judge said something" and "we have a verdict"."""

    @observe_phase(ActivityKind.GRADING)
    def rubric_verdict(request: Request) -> str:
        try:
            case_id, rubric_id = evidence_record_key(request.intent)
            record = build_evidence_record(
                request.context,
                case_id=case_id,
                rubric_id=rubric_id,
                producer_id=JUDGE_MODEL,
            )
        except ValueError as exc:
            raise _contract_error(str(exc)) from exc
        if record.get("valid") is not True:
            # WHY a transient error rather than a returned record: the expression's `;retry=` on
            # this route re-resolves the NESTED judge call, and that retry opts out of the gateway
            # cache (OME-1533, world/fresh_judge_retry.py), so each re-ask draws a fresh sample
            # instead of the stored garbled reply.
            # After the bounded retries the error propagates and the CASE fails loudly, keeping
            # the reply head as audit evidence.
            raw = str(record.get("raw_output") or "")
            raise ResolutionError(
                f"invalid judge reply for case {case_id} rubric {rubric_id} "
                f"({record.get('reason')}): {raw[:200]!r}",
                code="judge_reply_invalid",
                permanent=False,
            )
        accounting = accounting_for_grading_evidence(
            GradingEvidenceOwner(
                benchmark_id=benchmark_id,
                case_id=case_id,
                check_id=str(rubric_id),
                sequence=1,
            )
        )
        record["accounting"] = accounting.model_dump() if accounting is not None else None
        return compact_json(record)

    return rubric_verdict


@observe_phase(ActivityKind.GRADING)
def _rubric_evaluation(request: Request) -> str:
    try:
        case_id = positive_case_id(request.intent)
        payload = json_object(request.context, "GDPval rubric evaluation")
        # Exact keys in exact order — the payload comes from OUR expression's struct(), so any
        # drift means the expression and the runtime disagree.
        if tuple(payload) != ("case", "rubric", "evidence"):
            raise ValueError("GDPval rubric evaluation fields must be case, rubric, evidence")
        raw_case = json_object(payload["case"], "Case record")
        result = build_rubric_grade(
            case_id,
            raw_case or None,
            json_object(payload["rubric"], "Rubric record"),
            json_object(payload["evidence"], "Rubric verdict"),
        )
    except (TypeError, ValueError) as exc:
        raise _contract_error(str(exc)) from exc
    return compact_json(result)


def _scoring(
    root: Path,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
    mean: VariantMean,
):
    def aggregate_handler(selected_case_count: int):
        return reducing.scoring(
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
