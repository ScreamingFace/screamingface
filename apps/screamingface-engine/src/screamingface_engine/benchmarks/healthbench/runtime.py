"""Install HealthBench's private assets and deterministic functions into one Runner world.

If ``benchmark.py`` writes the recipe (the expression tree that names six routes),
this module is the kitchen: it registers a handler behind each of those routes so the
recipe can actually resolve. Every benchmark installs its own copy of them under its own
revision prefix, all reading one prepared answer key. Data flows through them in question order:

    /cases             → serve the selected question booklet (from the prepared assets)
    /rubric-tasks      → Candidate answered one Case: fetch its private rubric, render
                         one fully-built judge prompt per rubric item
    /rubric-verdict    → parse one judge reply into a verdict (or raise → retry)
    /rubric-evaluation → staple {case, rubric, verdict} into one row
    /case-evaluation   → collect a Case's rubric evaluations into its Case Evaluation
    /aggregate         → reduce all Case artifacts into the final score

Everything here is deterministic — the model calls live in the expression, not in
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
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.grading_endpoints import (
    candidate_answer,
    case_grade_endpoint,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.healthbench import grade as reducing
from screamingface_engine.benchmarks.healthbench import records
from screamingface_engine.benchmarks.healthbench.case_grade import (
    build_case_grade,
    build_rubric_grade,
)
from screamingface_engine.benchmarks.healthbench.check_policy import HEALTHBENCH_DRAFT_FEEDBACK
from screamingface_engine.benchmarks.healthbench.prompts import (
    build_grader_prompt,
    render_rubric_item,
)
from screamingface_engine.benchmarks.healthbench.revision_inputs import JUDGE_MODEL, JUDGE_PARAMS
from screamingface_engine.benchmarks.healthbench.variant import HealthbenchVariant, VariantMean
from screamingface_engine.benchmarks.healthbench.verdict import (
    build_evidence_record,
    evidence_record_key,
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


def install(node: Url4Node, root: Path, variant: HealthbenchVariant) -> None:
    """Register every route one HealthBench benchmark's expressions reference.

    Providers read lazily so a general-purpose Runner can carry the installed
    definition without HealthBench's private image assets — until an expression
    actually selects HealthBench, which is when the preflight below runs.

    INVARIANT: every benchmark is namespaced by its own id AND revision, so several benchmarks
    install into ONE Runner world over ONE ``root`` without colliding — which is exactly
    how the worst-30% challenge and the full professional variant coexist over a single
    prepared answer key.

    Args:
        node: the Runner world to register the routes in.
        root: the prepared HealthBench asset directory (shared by every benchmark).
        benchmark: which Cases this benchmark serves, at which addresses, under which final mean.
    """
    # Install the six routes that implement the benchmark's protocol.
    _install_protocol_once(
        node,
        root,
        cases_route=variant.routes.cases,
        judge_requests_route=variant.routes.judge_requests,
        verdict_route=variant.routes.verdict,
        rubric_evaluation_route=variant.routes.rubric_evaluation,
        case_evaluation_route=variant.routes.case_evaluation,
        aggregate_route=variant.routes.aggregate,
        check_surface_route=variant.routes.check_surface,
        benchmark_id=variant.id,
        benchmark_revision=variant.revision,
        case_ids=variant.case_ids,
        mean=variant.mean,
    )


def _install_protocol_once(
    node: Url4Node,
    root: Path,
    *,
    cases_route: str,
    judge_requests_route: str,
    verdict_route: str,
    rubric_evaluation_route: str,
    case_evaluation_route: str,
    aggregate_route: str,
    check_surface_route: str,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
    mean: VariantMean,
) -> None:
    install_cases(node, cases_route, _cases(root, case_ids))
    routes = frozenset(node.processor_routes())
    endpoints = (
        (
            aggregate_route + "/case-result",
            case_result_endpoint(
                _scoring(root, benchmark_id, benchmark_revision, case_ids, mean),
                available_case_count=len(case_ids),
            ),
        ),
        (judge_requests_route, _rubric_judge_requests(root, case_ids, benchmark_id)),
        # The mid-run check surface the corrective loop consumes. It closes over `node`
        # so the judge route resolves per request — installation must still work in a
        # world holding no model routes.
        (
            check_surface_route,
            rubric_draft_feedback_endpoint(node, root, HEALTHBENCH_DRAFT_FEEDBACK),
        ),
        (verdict_route, _rubric_verdict(benchmark_id)),
        (rubric_evaluation_route, _rubric_evaluation),
        (
            case_evaluation_route,
            case_grade_endpoint(
                label="HealthBench Case evaluation",
                item_name="Rubric evaluation",
                bind=build_case_grade,
                error_context_head=300,
            ),
        ),
        (
            aggregate_route,
            batch_result_endpoint(
                label="HealthBench",
                available_case_count=len(case_ids),
                load=_scoring(root, benchmark_id, benchmark_revision, case_ids, mean),
            ),
        ),
        (
            aggregate_route + "/graded",
            aggregate_result_endpoint(
                label="HealthBench",
                available_case_count=len(case_ids),
                load=_scoring(root, benchmark_id, benchmark_revision, case_ids, mean),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in routes:
            node.endpoint(route)(handler)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the prepared assets cannot serve this benchmark.

    A broken asset (missing cases.json, unreadable rubric) is knowable before any
    model runs. Without this check it would surface in the reducer — AFTER paying
    for the full Candidate + judge run, only to score None (review S-DR3). So the
    cases route runs this first: broken image → fail in seconds for free. The
    reducer still re-checks the same conditions (B1) — defense in depth.
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
        raise _definition_error("HealthBench assets failed preflight: " + "; ".join(problems[:8]))


def _cases(root: Path, case_ids: tuple[int, ...]):
    # Reference counterpart: the example selection at the top of the reference's
    # eval loop (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py)
    # — here the selection is this benchmark's case list, served from the prepared assets.
    @observe_phase(ActivityKind.CASE_LOADING)
    def cases() -> str:
        preflight(root, case_ids)
        raw = _read(root / "cases.json", "HealthBench cases")
        return json.dumps(_select_cases(raw, case_ids), ensure_ascii=False, separators=(",", ":"))

    return cases


def _rubric_judge_requests(root: Path, case_ids: tuple[int, ...], benchmark_id: str):
    # The fan-out point: one Candidate answer in, N ready-to-send judge requests out.
    # Receives the Candidate's output (context) + the Case id (intent); pulls the
    # PRIVATE rubric off disk — the first time the answer key touches the flow.
    # Reference counterpart: the prompt-construction half of `grade_sample`
    # (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py).
    @observe_phase(ActivityKind.GRADING)
    def rubric_judge_requests(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            report_case_grading(case_id, "started")
            answer = candidate_answer(request.context)
            evaluator_text = answer.text
            raw_cases = _read(root / "cases.json", "HealthBench cases")
            transcript = _transcript(raw_cases, case_id)
            items = _rubric_items(root, case_id)
            case_record = records.case_record(
                raw_cases,
                case_id=case_id,
                candidate=answer,
            )
            judge_requests: list[dict[str, str]] = []
            for item in items:
                rendered = render_rubric_item(item["points"], item["criterion"])
                grader_prompt = build_grader_prompt(transcript, evaluator_text, rendered)
                owner = GradingEvidenceOwner(
                    benchmark_id=benchmark_id,
                    case_id=case_id,
                    check_id=str(item["rubric_id"]),
                    sequence=1,
                )
                register_grading_request(
                    owner,
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
                        # INVARIANT: the judge prompt is fully rendered HERE, engine-
                        # side, so its bytes match the reference `grade_sample` exactly
                        # — nothing about the prompt is assembled inside the expression.
                        "grader_prompt": grader_prompt,
                        # Dedup: the full Case record (Candidate's whole output) rides
                        # the FIRST task only; the rest carry "{}" — case_grade.py
                        # hoists it back to one record per Case.
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
    # The parse gate between "the judge said something" and "we have a verdict":
    # context = the raw judge reply, intent = "case_id:rubric_id" (Engine-stamped,
    # never trusted from the judge).
    # Reference counterpart: the parse-and-retry half of `grade_sample`
    # (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py).
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
            # WHY transient, not a returned record: the expression's `;retry=` on this
            # route re-resolves the NESTED judge call, and that retry opts out of the
            # gateway cache (OME-1533, world/fresh_judge_retry.py), so each re-ask draws a
            # fresh sample at provider-default temperature — the reference's retry mechanism,
            # bounded (`grade_sample` loops forever on the same condition). After the
            # bounded retries the error propagates and the CASE fails loudly, keeping
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
        payload = json_object(request.context, "HealthBench rubric evaluation")
        # Exact keys in exact order — the payload comes from OUR expression's struct()
        # (definition.py), so any drift means the expression and runtime disagree.
        if tuple(payload) != ("case", "rubric", "evidence"):
            raise ValueError("HealthBench rubric evaluation fields must be case, rubric, evidence")
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


def _transcript(raw_cases: str, case_id: int) -> str:
    """The reference's judge/display form — ``"role: content"`` turns joined by blank lines.

    Reference counterpart: how ``grade_sample`` flattens the conversation before
    substituting it into ``<<conversation>>``
    (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py) — the
    judge must see the transcript in exactly these bytes.
    """

    for row in json.loads(raw_cases):
        if isinstance(row, Mapping) and row.get("id") == case_id:
            envelope = json.loads(str(row.get("input")))
            if (
                not isinstance(envelope, Mapping)
                or envelope.get("schema") != CANDIDATE_INPUT_SCHEMA
            ):
                raise ValueError(f"HealthBench case {case_id} input is not a chat envelope")
            messages = envelope.get("messages")
            decoded = json.loads(messages) if isinstance(messages, str) else messages
            if not isinstance(decoded, list) or not decoded:
                raise ValueError(f"HealthBench case {case_id} carries no messages")
            return "\n\n".join(
                f"{turn.get('role')}: {turn.get('content')}"
                for turn in decoded
                if isinstance(turn, Mapping)
            )
    raise ValueError(f"unknown HealthBench case {case_id}")


def _rubric_items(root: Path, case_id: int) -> list[dict[str, Any]]:
    path = root / "rubrics" / f"{case_id}.json"
    decoded = json.loads(_read(path, f"HealthBench rubric {case_id}"))
    items = decoded.get("items") if isinstance(decoded, Mapping) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"HealthBench rubric {case_id} carries no items")
    return items


def _select_cases(raw: str, case_ids: tuple[int, ...]) -> list[dict[str, object]]:
    try:
        cases = json.loads(raw)
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            raise ValueError("expected a JSON array of objects")
        by_id = {case["id"]: case for case in cases}
        return [by_id[case_id] for case_id in case_ids]
    except (KeyError, TypeError, ValueError) as exc:
        raise _unavailable(f"could not select HealthBench cases {case_ids}: {exc}") from exc


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = ["install", "preflight"]
