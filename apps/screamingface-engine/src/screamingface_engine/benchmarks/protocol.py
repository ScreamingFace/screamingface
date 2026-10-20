"""URL4 composition shared by Engine-owned Benchmarks.

FEATURE: one Benchmark run is one URL4 expression that reads as URL4 Parts A–C define it
(spec ``docs/spec/2026-10-20-url4-benchmark-expression-spec.md``)::

    (
      evaluations:0.0:/benchmarks/<id>/<rev>/cases*(
        case:0.0:$item,
        attempt_1:0.0:/benchmarks/candidate?web_search=false&q=(
          case_id=$item.id, case_index=$index, case_count='3', recipe=$candidate
        )!'$item.input'
      )!/benchmarks/<id>/<rev>/case-evaluation;iteration.concurrency=1;iteration.slice=0:3,
      selected:0.0:'3'
    )!/benchmarks/<id>/<rev>/aggregate

- R1: a deterministic step is an RDS intent — a code pointer the Engine mounts with
  ``node.code`` — and its named sources are the code's input contract.
- R2: a model call is LLM mode — the quoted intent is the prompt.
- R3: the case set is a data reference (no ``!``); ``;iteration.slice`` selects the Cases.
- R4: the nesting is the pipeline — the run terminal is the outer intent, the per-Case
  terminal is the iteration body's intent, and each per-Case step is a body source.
- R7: no quoted intent is a label, a count or a projection.
"""

from __future__ import annotations

from collections.abc import Sequence

from screamingface_engine.benchmarks.definition import candidate_invocation
from screamingface_engine.benchmarks.grading_endpoints import positive_count
from url4 import Node, RelUrl, Text, VarRef, expr, iterate, src
from url4.core.nodes import Expression

# INVARIANT (D5, owner 2026-10-20): unchanged when the expression was rebuilt. The rows, the
# grading and the model-call bytes did not move, so no Benchmark revision id may move.
EVALUATION_PROTOCOL_REVISION = "outcome-preserving-case-evaluation-v1"

CASE_SOURCE = "case"
EVALUATIONS_SOURCE = "evaluations"
SELECTED_SOURCE = "selected"


def attempt_source(number: int) -> str:
    """The body source name of Attempt ``number`` (``attempt_1`` … ``attempt_N``)."""

    return f"attempt_{positive_count(number, 'attempt')}"


def evaluation_protocol(
    *,
    cases_route: str,
    steps: Sequence[Node],
    case_terminal: str,
    run_terminal: str,
    selected_case_count: int,
    available_case_count: int,
) -> Expression:
    """Compose the ordered per-Case pipeline and the run terminal around ``steps``.

    ``steps`` are the per-Case body sources after ``case``; ``case_terminal`` and
    ``run_terminal`` are code pointers the Benchmark mounts.

    WHY concurrency 1: Case admission covers the whole spawned row; nested Case work keeps
    its own cap. NOTE (OME-1458): it bounds Cases, not Attempts — the Attempts of one Case are
    sibling body sources and may run side by side.
    """

    for value, label in (
        (cases_route, "cases_route"),
        (case_terminal, "case_terminal"),
        (run_terminal, "run_terminal"),
    ):
        _route(value, label)
    positive_count(available_case_count, "available_case_count")
    positive_count(selected_case_count, "selected_case_count")
    if selected_case_count > available_case_count:
        raise ValueError("selected_case_count cannot exceed available_case_count")
    if any(not isinstance(step, Node) for step in steps):
        raise TypeError("steps must contain only URL4 Nodes")

    evaluations = iterate(
        RelUrl(cases_route),
        body=(src(VarRef("item", ()), name=CASE_SOURCE, weight=0.0), *steps),
        intent=RelUrl(case_terminal),
        concurrency=1,
        slice=(0, selected_case_count),
        on_error="collect",
    )
    return expr(
        src(evaluations, name=EVALUATIONS_SOURCE, weight=0.0),
        src(Text(str(selected_case_count)), name=SELECTED_SOURCE, weight=0.0),
        intent=RelUrl(run_terminal),
    )


def attempt_steps(
    prompt: str,
    *,
    attempts: int,
    case_count: int,
    web_search: bool,
    web_search_exclude: Sequence[str] = (),
) -> tuple[Node, ...]:
    """``attempt_1`` … ``attempt_N``: one Candidate Invocation of ``prompt`` per Attempt.

    INVARIANT (OME-1458): Attempt 2 and later carry their number on the call, so an unseeded
    run is never served Attempt 1's stored reply.
    """

    positive_count(attempts, "attempts")
    return tuple(
        src(
            candidate_invocation(
                prompt,
                case_count=case_count,
                web_search=web_search,
                web_search_exclude=web_search_exclude,
                attempt=number,
            ),
            name=attempt_source(number),
            weight=0.0,
        )
        for number in range(1, attempts + 1)
    )


def _route(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{label} must be an absolute URL4 path")
    return value


__all__ = [
    "CASE_SOURCE",
    "EVALUATIONS_SOURCE",
    "EVALUATION_PROTOCOL_REVISION",
    "SELECTED_SOURCE",
    "attempt_source",
    "attempt_steps",
    "evaluation_protocol",
]
