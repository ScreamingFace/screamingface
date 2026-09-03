"""URL4 composition capabilities shared by Engine-owned Benchmarks."""

from __future__ import annotations

from screamingface_engine.benchmarks.case_execution import CASE_EXECUTION_ROUTE
from screamingface_engine.benchmarks.evaluation import positive_count
from url4 import Node, RelExpr, Text, expr, iterate, render, src, struct

EVALUATION_PROTOCOL_REVISION = "outcome-preserving-case-evaluation-v1"


def preserve_candidate_outcome(
    *,
    candidate_invocation: Node,
    grading: Node,
    case_id: str,
) -> Node:
    """Keep one completed Candidate Invocation even when later grading fails."""

    if not isinstance(candidate_invocation, Node):
        raise TypeError("candidate_invocation must be a URL4 Node")
    if not isinstance(grading, Node):
        raise TypeError("grading must be a URL4 Node")
    if not isinstance(case_id, str) or not case_id:
        raise TypeError("case_id must be non-empty URL4 text")
    protected_grading = iterate(
        [
            struct(
                {
                    "candidate_invocation": "$candidate_invocation",
                    "case_id": case_id,
                }
            )
        ],
        body=(src(grading, name="grading", weight=0.0),),
        intent=Text("$grading"),
        on_error="collect",
    )
    case_execution = expr(
        src(candidate_invocation, name="candidate_invocation", weight=0.0),
        src(protected_grading, name="protected_grading", weight=0.0),
        src(
            RelExpr(
                path=CASE_EXECUTION_ROUTE,
                context=render(
                    struct(
                        {
                            "case_id": case_id,
                            "candidate_invocation": "$candidate_invocation",
                            "grading": "$protected_grading",
                        }
                    )
                ),
                intent=Text(""),
            ),
            name="case_execution",
            weight=0.0,
        ),
        intent=Text("$case_execution"),
    )
    return expr(
        src(case_execution, name="preserved_case", weight=0.0),
        intent=Text("$preserved_case"),
    )


def build_evaluation_protocol(
    *,
    cases_route: str,
    case_evaluation: Node,
    selected_case_count: int,
    available_case_count: int,
    aggregate_route: str,
    bindings: tuple[Node, ...] = (),
) -> Node:
    """Compose ordered Case evaluation and typed Aggregation around one Case node."""

    _route(cases_route, "cases_route")
    _route(aggregate_route, "aggregate_route")
    positive_count(available_case_count, "available_case_count")
    positive_count(selected_case_count, "selected_case_count")
    if selected_case_count > available_case_count:
        raise ValueError("selected_case_count cannot exceed available_case_count")
    if not isinstance(case_evaluation, Node):
        raise TypeError("case_evaluation must be a URL4 Node")
    if any(not isinstance(binding, Node) for binding in bindings):
        raise TypeError("bindings must contain only URL4 Nodes")

    # INVARIANT: Case admission covers the complete spawned row; nested Case work keeps its cap.
    case_evaluations = iterate(
        cases_route,
        body=(src(case_evaluation, name="evaluated", weight=0.0),),
        intent=Text("$evaluated"),
        concurrency=1,
        slice=(None if selected_case_count == available_case_count else (0, selected_case_count)),
        on_error="collect",
    )
    selected_case_evaluations = expr(
        *bindings,
        src(case_evaluations, name="selected_case_evaluations", weight=0.0),
        intent=Text("$selected_case_evaluations"),
    )
    return expr(
        src(selected_case_evaluations, name="case_evaluations", weight=0.0),
        src(
            RelExpr(
                path=aggregate_route,
                context="$case_evaluations",
                intent=Text(f"aggregate:{selected_case_count}"),
            ),
            name="result",
            weight=0.0,
        ),
        intent=Text("$result"),
    )


def _route(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{label} must be an absolute URL4 path")
    return value


__all__ = [
    "EVALUATION_PROTOCOL_REVISION",
    "build_evaluation_protocol",
    "preserve_candidate_outcome",
]
