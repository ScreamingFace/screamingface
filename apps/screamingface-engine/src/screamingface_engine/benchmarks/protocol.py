"""URL4 composition capabilities shared by Engine-owned Benchmarks."""

from __future__ import annotations

import re
from dataclasses import replace

from screamingface_engine.benchmarks.case_request import CASE_ATTEMPT_PARAM
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE
from screamingface_engine.benchmarks.graded_answer import CASE_ATTEMPTS_ROUTE, GRADED_ANSWER_ROUTE
from screamingface_engine.benchmarks.grading_endpoints import positive_count
from url4 import Node, RelExpr, Text, expr, iterate, render, src, struct
from url4.core.nodes import Expression, Iteration, RemoteExpr, Source, StructObject, walk

EVALUATION_PROTOCOL_REVISION = "outcome-preserving-case-evaluation-v1"

# A Candidate Invocation written inside a template string (an ``iterate`` body, a context): the
# route followed by anything but more path, so a longer route sharing the prefix is not counted.
_CANDIDATE_ROUTE_IN_TEXT = re.compile(re.escape(CANDIDATE_ROUTE) + r"(?![\w/.-])")


def preserve_candidate_outcome(
    *,
    candidate_invocation: Node,
    grading: Node,
    case_id: str,
    bindings: tuple[Node, ...] = (),
    attempts: int = 1,
) -> Node:
    """Keep one completed Candidate Invocation even when later grading fails.

    ``attempts`` (OME-1458) is the Benchmark's declared Attempts per Case. At 1 the
    expression is exactly the one-Attempt expression below, so no published Benchmark's URL4
    moves. Above 1 the Case runs that same execution N times — Attempt i's Candidate
    Invocation carries ``attempt=i`` for i ≥ 2, so its model calls are never served Attempt
    1's stored reply — and the N envelopes are joined into one Attempts row the marking room
    folds per Check. The ``bindings`` run again inside every Attempt: one Attempt is one
    complete answer.

    AIDEV-NOTE: a failed Candidate Invocation in ANY Attempt fails the whole Case, as it does
    for a one-Attempt Case today. Only `iterate` collects errors, and it rebinds `$item` and
    `$index`, which the Benchmark's own nodes read; a failed Grading stays per Attempt.

    ``bindings`` are case-scope sources resolved BEFORE the candidate invocation, for
    values both the invocation and the grading depend on (e.g. MedXpertQA's turn-1
    reasoning). WHY here and not inside ``grading``: the protective iterate rebinds
    ``$item`` to the ``{candidate_invocation, case_id}`` struct, so a grading-scope
    node can no longer read the case row — a `$item.<field>` reference there silently
    resolves empty and ships an empty model prompt (OME-1126 live-run evidence).
    """

    if not isinstance(candidate_invocation, Node):
        raise TypeError("candidate_invocation must be a URL4 Node")
    if not isinstance(grading, Node):
        raise TypeError("grading must be a URL4 Node")
    if not isinstance(case_id, str) or not case_id:
        raise TypeError("case_id must be non-empty URL4 text")
    if any(not isinstance(binding, Node) for binding in bindings):
        raise TypeError("bindings must contain only URL4 Nodes")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if attempts == 1:
        return _preserved_case(candidate_invocation, grading, case_id, bindings)
    return _attempted_case(candidate_invocation, grading, case_id, bindings, attempts)


def _preserved_case(
    candidate_invocation: Node, grading: Node, case_id: str, bindings: tuple[Node, ...]
) -> Node:
    """One Attempt: the Candidate Invocation, its protected Grading, and the envelope."""

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
        *bindings,
        src(candidate_invocation, name="candidate_invocation", weight=0.0),
        src(protected_grading, name="protected_grading", weight=0.0),
        src(
            RelExpr(
                path=GRADED_ANSWER_ROUTE,
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


def _attempted_case(
    candidate_invocation: Node,
    grading: Node,
    case_id: str,
    bindings: tuple[Node, ...],
    attempts: int,
) -> Node:
    """N Attempts of one Case, each a full one-Attempt execution, joined into one row.

    Worked example, ``attempts=2``: ``attempt_1`` is today's execution; ``attempt_2`` is the
    same execution with ``attempt=2`` on every Candidate Invocation inside it; the
    case-attempts route returns ``{schema, case_id, attempts: [envelope 1, envelope 2]}``.

    WHY siblings: the N executions are independent sources of one expression, so URL4 may run
    them side by side inside the Case; the joined row keeps them in Attempt order whichever
    finishes first. Cases still run one at a time (the per-Case iterate's concurrency of 1).
    """

    executions: list[Node] = []
    for number in range(1, attempts + 1):
        invocation, numbered_bindings = _numbered_or_refused(candidate_invocation, bindings, number)
        executions.append(
            src(
                _preserved_case(invocation, grading, case_id, numbered_bindings),
                name=f"attempt_{number}",
                weight=0.0,
            )
        )
    names: list[str] = [f"attempt_{number}" for number in range(1, attempts + 1)]
    joined = RelExpr(
        path=CASE_ATTEMPTS_ROUTE,
        context=render(struct({"case_id": case_id, **{name: f"${name}" for name in names}})),
        intent=Text(""),
    )
    return expr(
        *executions,
        src(joined, name="preserved_case", weight=0.0),
        intent=Text("$preserved_case"),
    )


def _numbered_or_refused(
    candidate_invocation: Node, bindings: tuple[Node, ...], attempt: int
) -> tuple[Node, tuple[Node, ...]]:
    """The Candidate Invocation and bindings marked as Attempt ``attempt``, or a refusal.

    INVARIANT: Attempt 2 and later carry their number on EVERY Candidate Invocation.
    An unmarked call in Attempt 2 leaves the Engine byte-identical to Attempt 1's call, so an
    unseeded run is served Attempt 1's stored reply and the board silently scores one answer
    N times. ``_numbered`` walks only Expressions and Sources; a Candidate Invocation nested
    inside another node kind (an ``iterate``, a struct) is not reached, and this raise is how
    the Benchmark author finds out, at build time, before any paid call.

    Think of it as a head count: count every Candidate Invocation the Attempt will send, then
    count the ones the rewrite numbered; any shortfall refuses. Worked example: a reachable
    final call beside a reasoning call inside an ``iterate`` binding → 2 sent, 1 numbered →
    refused, because the reasoning call would replay Attempt 1's answer.
    """

    nodes: tuple[Node, ...] = (candidate_invocation, *bindings)
    parts: list[tuple[Node, int]] = [_numbered(node, attempt) for node in nodes]
    if attempt > 1:
        numbered: int = sum(count for _, count in parts)
        sent: int = sum(_candidate_invocations(node) for node in nodes)
        if numbered == 0:
            raise ValueError(
                f"Attempt {attempt} reached no Candidate Invocation on {CANDIDATE_ROUTE}: it "
                "would be sent identical to Attempt 1; build the Candidate Invocation as an "
                "expression or source the Attempts rewrite can reach (OME-1458)"
            )
        if numbered < sent:
            raise ValueError(
                f"Attempt {attempt} numbered {numbered} of {sent} Candidate Invocations on "
                f"{CANDIDATE_ROUTE}: a Candidate Invocation sits where the Attempt number cannot "
                "reach (inside an iterate or another node kind), so it would be sent identical "
                "to Attempt 1's; build every Candidate Invocation as an expression or source "
                "the Attempts rewrite can reach (OME-1458)"
            )
    return parts[0][0], tuple(node for node, _ in parts[1:])


def _candidate_invocations(node: Node) -> int:
    """Count every Candidate Invocation inside ``node``, reachable by the rewrite or not.

    WHY text too: an ``iterate`` keeps its body (and a call keeps its context) as a template
    string, not as nodes, so a Candidate Invocation there is visible only as its route.
    """

    count: int = 0
    for child in walk(node):
        texts: tuple[str | None, ...] = ()
        if isinstance(child, RelExpr | RemoteExpr):
            count += int(isinstance(child, RelExpr) and child.path == CANDIDATE_ROUTE)
            texts = (child.context,)
        elif isinstance(child, Iteration):
            texts = (child.body, child.intent, child.reducer)
        elif isinstance(child, StructObject):
            texts = (child.raw,)
        count += sum(len(_CANDIDATE_ROUTE_IN_TEXT.findall(text)) for text in texts if text)
    return count


def _numbered(node: Node, attempt: int) -> tuple[Node, int]:
    """Mark every Candidate Invocation inside ``node`` as Attempt ``attempt``; 1 is unmarked.

    Returns the rewritten node and how many Candidate Invocations it marked (0 at Attempt 1).

    WHY a rewrite of the Benchmark's own node instead of a second builder argument: the
    Benchmark built one Candidate Invocation, and Attempt i must be exactly it plus the
    number, so nothing else about the request can drift between Attempts.
    """

    selected: Node = node
    rewrites: int = 0
    if attempt == 1:
        pass
    elif isinstance(node, RelExpr) and node.path == CANDIDATE_ROUTE:
        selected = replace(node, params=(*node.params, (CASE_ATTEMPT_PARAM, str(attempt))))
        rewrites = 1
    elif isinstance(node, Source):
        value, rewrites = _numbered(node.value, attempt)
        selected = replace(node, value=value)
    elif isinstance(node, Expression):
        parts: list[tuple[Node, int]] = [_numbered(item, attempt) for item in node.sources]
        selected = replace(node, sources=tuple(item for item, _ in parts))
        rewrites = sum(count for _, count in parts)
    return selected, rewrites


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
    # NOTE (OME-1458): concurrency=1 bounds Cases, not Attempts. The Attempts of one Case are
    # sibling sources and may run side by side; when one fails the run's TaskGroup cancels
    # its in-flight siblings, whose provider spend is not recorded (spec §4).
    case_evaluations = iterate(
        RelExpr(path=cases_route, intent=Text(str(selected_case_count))),
        body=(src(case_evaluation, name="evaluated", weight=0.0),),
        intent=Text("$evaluated"),
        concurrency=1,
        slice=(0, selected_case_count),
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
    "early_result",
    "EVALUATION_PROTOCOL_REVISION",
    "build_evaluation_protocol",
    "preserve_candidate_outcome",
]


def early_result(execution: Node, *, aggregate_route: str, selected_case_count: int) -> Node:
    """Carry the canonical grade into aggregation before admitting the next case."""
    return expr(
        src(execution, name="execution", weight=0.0),
        src(
            RelExpr(
                path=aggregate_route + "/case-result",
                context="$execution",
                intent=Text(f"$index:{selected_case_count}"),
            ),
            name="graded",
            weight=0.0,
        ),
        intent=Text("$graded"),
    )
