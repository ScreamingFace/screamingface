"""Versioned constants for the benchmark-independent corrective loop.

FEATURE: OME-796 — the LANL corrective protocol as a generic capability. The
client compiles the ENTIRE loop (member fan-out, rounds, gates, select) into one
whole-`$candidate` expression; the engine contributes generic invocation and
control-flow endpoints under `CORRECTIVE_PREFIX` plus each benchmark's advertised
draft-feedback offer. Everything here is Engine-owned transport contract: the Client
mirrors these route strings when it renders a loop expression, so any change is
a protocol change. Client-authored loop prose and its identity hash remain with
the compiler that places that prose into the expression.
"""

from __future__ import annotations

# WHY a version segment instead of a revision hash in the route: the client
# renders these routes into candidate expressions without fetching them from any
# manifest (they are engine capability, not benchmark surface — the same class of
# wire constant as /benchmarks/candidate). A semantic change to gate/select
# semantics ships as /v2 routes; the runtime's decision-table tests pin the
# semantics implemented by each route.
CORRECTIVE_API_VERSION = "v1"
CORRECTIVE_PREFIX = f"/ensemble/corrective/{CORRECTIVE_API_VERSION}"
GATE_ROUTE = f"{CORRECTIVE_PREFIX}/gate"
SELECT_ROUTE = f"{CORRECTIVE_PREFIX}/select"
ANSWER_ROUTE = f"{CORRECTIVE_PREFIX}/answer"
MEMBER_ROUTE = f"{CORRECTIVE_PREFIX}/member"
ROLE_ROUTE = f"{CORRECTIVE_PREFIX}/role"
RESULT_ROUTE = f"{CORRECTIVE_PREFIX}/result"

# The check-surface port record — every benchmark adapter returns exactly this
# shape: {schema, passed: bool, satisfaction: float in [0,1], feedback: sanitized
# text, answer: evaluator text, invocation: exact Candidate Invocation}. `passed`
# replaces the old "PASSED" feedback
# sentinel; `satisfaction` replaces the IFEval-private `_strict_satisfaction`
# call inside gate/select (each benchmark computes its own behind the adapter).
DRAFT_FEEDBACK_SCHEMA = "screamingface.check-surface.v1"

# Member identity uses unbounded spreadsheet-style lowercase labels so the
# generic substrate does not inherit the LANL prototype's 2..4 bound.
MEMBER_LABEL_SCHEME = "lowercase-base26"


def member_labels(count: int) -> tuple[str, ...]:
    """Return stable lowercase labels: a..z, aa..az, ba..."""

    return tuple(_member_label(index) for index in range(count))


def _member_label(index: int) -> str:
    value = index + 1
    selected = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        selected = chr(ord("a") + remainder) + selected
    return selected


__all__ = [
    "ANSWER_ROUTE",
    "DRAFT_FEEDBACK_SCHEMA",
    "CORRECTIVE_API_VERSION",
    "CORRECTIVE_PREFIX",
    "GATE_ROUTE",
    "MEMBER_LABEL_SCHEME",
    "MEMBER_ROUTE",
    "RESULT_ROUTE",
    "ROLE_ROUTE",
    "SELECT_ROUTE",
    "member_labels",
]
