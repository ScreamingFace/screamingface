"""Guard: no spec the engine accepts can choose a member its rule excluded (E4b part 2, P2 #2).

FEATURE: the endpoint marks a member ``excluded`` from the step's rule (``_exclusion``: a signal
weight it does not have, or a signal the reduce args read and it does not have), not from a report
of the operator. The guard runs every reducer, reduce op and select op pairing the rule tables
accept (``REDUCER_RULES``, the registry, ``REDUCE_SELECT_RULES``) over members that the rule leaves
out, and checks that no such member is ever chosen.
STORY: as the engine owner, a new operator or a new pairing that could choose an excluded member
fails here, not as a crash of a real call on the evidence check (CE-I3).
INVARIANT: a run ends in a declared ``CombineError`` (the engine refused it) or in evidence whose
``chosen`` holds no excluded member. Any other exception is a crash and fails the guard.
WHY one field signal: the exclusion rule reads the signal number the core put on each member; where
the number came from (a field, the judge, an accounting reader) does not change the rule.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.ports import CombineError
from screamingface_engine.combine.spec import REDUCE_SELECT_RULES, REDUCER_RULES, Presence

_KEY = "field:confidence"
_MEMBERS = ["member_1", "member_2", "member_3"]

# Valid args for every registered reduce and select op; the coverage test below keeps it complete.
_ARGS: Mapping[str, list[dict[str, Any]]] = {
    "by_signal@1": [{"key": _KEY, "order": "max"}, {"key": _KEY, "order": "min"}],
    "field_rules@1": [{"fields": [{"field": "answer", "rule": "majority", "normalize": "text"}]}],
    "filter@1": [
        {"key": _KEY, "cmp": "ge", "value": 0.5},
        {"key": _KEY, "cmp": "lt", "value": 0.5},
        {"pattern": "answer"},
    ],
    "join@1": [{"separator": "\n---\n", "label": False}],
    "label@1": [{}],
    "mean@1": [{}],
    "median@1": [{}],
    "mode@1": [{}],
    "project_field@1": [{"field": "answer"}],
    "scores@1": [{"source": "values"}, {"source": "judge"}],
    "values@1": [{"field": "confidence"}],
    "weighted_mean@1": [{}],
    "weighted_median@1": [{}],
    "weighted_mode@1": [{}],
    "all@1": [{}],
    "best_holder@1": [{"order": "max"}, {"order": "min"}],
    "built@1": [{}],
    "by_field@1": [{"order": "max"}, {"order": "min"}],
    "by_label@1": [{}],
    "first_holder@1": [{}],
    "kept@1": [{}],
    "max_score@1": [{}],
    "max_weight_holder@1": [{}],
    "nearest@1": [{}],
    "top_k@1": [{"k": 1}, {"k": 2}, {"k": 3}, {"k": 1, "order": "min"}, {"k": 2, "order": "min"}],
    "value@1": [{}],
}

_EXTRACTS = [
    {"op": "json_field@1", "args": {"path": "answer"}},
    {"op": "json_object@1", "args": {}},
]
_NORMALIZES = [{"op": "text@1", "args": {}}, {"op": "numeric@1", "args": {}}]
_WEIGHTS = [{"signal": _KEY}, dict.fromkeys(_MEMBERS, 1.0)]


def _reply(answer: str, confidence: float | None = None) -> str:
    body: dict[str, Any] = {"answer": answer}
    if confidence is not None:
        body["confidence"] = confidence
    return json.dumps(body)


# Each set leaves one or two members without the signal; an excluded member sits first, last, on
# the winning value, at the extreme field value, or alone with no reply field at all.
_OUTPUT_SETS = [
    [_reply("1"), _reply("1", 0.9), _reply("3", 0.2)],
    [_reply("1", 0.9), _reply("3", 0.2), _reply("1")],
    [_reply("3"), _reply("1", 0.9), _reply("1", 0.2)],
    [_reply("1"), _reply("2"), _reply("3", 0.2)],
    ["{}", _reply("1", 0.8), _reply("1", 0.2)],
    [_reply("5"), _reply("1", 0.1), _reply("9", 0.9)],
    [_reply("9"), _reply("1", 0.1), _reply("5", 0.6)],
]
# The judge ops read a judge reply: a label (label@1) or one score per member (scores@1). WHY
# only for them: no other op reads the reply, so a run with it would repeat a run without it.
_SIGNALS: Mapping[str, list[dict[str, str] | None]] = {
    "label@1": [{"judge": "member_1"}],
    "scores@1": [None, {"judge": json.dumps({"member_1": 9, "member_2": 1, "member_3": 5})}],
}


def _ops(stage: str) -> list[str]:
    return [descriptor.id for descriptor in BUILTIN_OPERATORS if descriptor.stage == stage]


def _choices(presence: Presence, options: list[Any]) -> list[Any]:
    return {"required": options, "optional": [None, *options], "forbidden": [None]}[presence]


def _specs(reduce: str, select: str) -> Iterator[dict[str, Any]]:
    """Every spec of this reduce/select pairing that the presence rules of a reducer allow."""
    for reducer, rule in REDUCER_RULES.items():
        normalizes = [
            step
            for step in _NORMALIZES
            if rule.normalize_name is None or step["op"].startswith(f"{rule.normalize_name}@")
        ]
        for extract, normalize, weights, reduce_args, select_args in itertools.product(
            _choices(rule.extract, _EXTRACTS),
            _choices(rule.normalize, normalizes),
            _choices(rule.weights, _WEIGHTS),
            _ARGS[reduce],
            _ARGS[select],
        ):
            yield {
                "schema": "screamingface.combine-spec.v1",
                "reducer": reducer,
                "members": _MEMBERS,
                "extract": extract,
                "normalize": normalize,
                "reduce": {"op": reduce, "args": reduce_args},
                "select": {"op": select, "args": select_args},
                "weights": weights,
            }


def _outcomes(reduce: str, select: str) -> Iterator[CombineOutcome]:
    """Each run the engine completes (answered or abstained); a refused run is skipped."""
    for spec in _specs(reduce, select):
        intent = spec_text(spec)
        for outputs, signals in itertools.product(_OUTPUT_SETS, _SIGNALS.get(reduce, [None])):
            try:
                yield run(intent, context_text(outputs, signals), registry=BUILTIN_OPERATORS)
            except CombineError:
                continue  # a declared refusal: the engine does not accept this run


_PAIRS = list(itertools.product(_ops("reduce"), _ops("select")))


def test_every_registered_reduce_and_select_op_has_guard_args() -> None:
    assert set(_ops("reduce")) | set(_ops("select")) <= set(_ARGS)


@pytest.mark.parametrize(("reduce", "select"), _PAIRS, ids=[f"{r}+{s}" for r, s in _PAIRS])
def test_an_excluded_member_is_never_chosen(reduce: str, select: str) -> None:
    for outcome in _outcomes(reduce, select):
        evidence = outcome.evidence
        excluded = {row.member_id for row in evidence.members if row.status == "excluded"}
        assert not excluded & set(evidence.chosen)


_ALLOWED = [
    (reduce, select)
    for reduce, selects in sorted(REDUCE_SELECT_RULES.items())
    for select in sorted(selects)
]


@pytest.mark.parametrize(("reduce", "select"), _ALLOWED, ids=[f"{r}+{s}" for r, s in _ALLOWED])
def test_the_guard_runs_see_excluded_members(reduce: str, select: str) -> None:
    """The guard is not empty: every allowed pairing completes with an excluded member."""
    assert any(
        row.status == "excluded"
        for outcome in _outcomes(reduce, select)
        for row in outcome.evidence.members
    )


def test_every_reduce_op_that_can_exclude_a_member_is_in_the_rule_table() -> None:
    excluding = {
        descriptor.id
        for descriptor in BUILTIN_OPERATORS
        if descriptor.stage == "reduce"
        and (descriptor.reads_weights or descriptor.signal_read is not None)
    }

    assert excluding <= set(REDUCE_SELECT_RULES)


def test_the_rule_table_names_only_registered_ops() -> None:
    registered = set(_ops("reduce")) | set(_ops("select"))
    for reduce, selects in REDUCE_SELECT_RULES.items():
        assert reduce in _ops("reduce")
        assert selects <= registered
