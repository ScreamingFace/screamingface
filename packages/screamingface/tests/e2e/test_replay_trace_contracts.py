"""Contract tests for the RT-4 trace drift rule (OME-1289 E4a, RT#16).

DEFAULT lane: pure data, no stack. The replay lanes hold a cached replay's trace to the live run's
trace with ``trace_drift``, so the rule that decides what may differ is pinned here, before any
paid recording exists. Only the accounting of a model call may move: a cache hit has another
``cache`` status, no ``cost_usd`` of its own, and so on.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from harness.replay_trace import MODEL_CALL_ACCOUNTING, trace_drift

from screamingface.report_trace import TRACE_FIELDS, TRACE_SCHEMA

type Trace = dict[str, Any]


def _entries(case_id: int) -> list[dict[str, Any]]:
    member = f"member_{case_id}"
    return [
        {
            "kind": "model_call",
            "operation_id": "op_model_1",
            "member_id": member,
            "provider": "prov",
            "model": "openrouter/prov/model-x",
            "cache": {"status": "miss"},
            "cost_usd": 0.001,
            "latency_ms": 120,
            "tokens_in": 10,
            "tokens_out": 4,
            "status": "ok",
        },
        {
            "kind": "extract",
            "operation_id": "op_synthesis_1",
            "member_id": member,
            "rule": "last_number@1",
            "raw": "42",
            "value": "42",
            "status": "answered",
            "reason": None,
        },
        {
            "kind": "reduce",
            "operation_id": "op_synthesis_1",
            "op": "mode@1",
            "rule": "vote",
            "mode": "compute",
            "tally": [{"value": "42", "score": 1.0, "holders": [member]}],
            "chosen": [member],
            "signal": {"key": "cost_usd", "values": {member: 0.001}},
            "result": {"member_id": member, "status": "answered"},
            "dropped": 0,
        },
    ]


def _trace() -> Trace:
    cases = [{"case_id": case_id, "entries": _entries(case_id)} for case_id in (1, 2)]
    return {
        "schema": TRACE_SCHEMA,
        "candidates": [{"candidate": "vote", "cases": cases}],
    }


def test_the_helper_trace_uses_the_real_entry_fields() -> None:
    # Guard: the helper must not drift from the SDK's closed field sets.
    assert set(MODEL_CALL_ACCOUNTING) <= set(TRACE_FIELDS["model_call"])


def test_identical_traces_have_no_drift() -> None:
    assert trace_drift(_trace(), copy.deepcopy(_trace())) == ()


def _first_model_call(trace: Trace, case: int = 0) -> dict[str, Any]:
    return trace["candidates"][0]["cases"][case]["entries"][0]


def test_model_call_accounting_may_differ() -> None:
    replay = _trace()
    for key in MODEL_CALL_ACCOUNTING:
        replay["candidates"][0]["cases"][0]["entries"][0][key] = (
            {"status": "hit"} if key == "cache" else None
        )

    assert trace_drift(_trace(), replay) == ()


_CASE = "candidates[0].cases[0]"


def _set_entry(index: int, key: str, value: object) -> Callable[[Trace], None]:
    def mutate(trace: Trace) -> None:
        trace["candidates"][0]["cases"][0]["entries"][index][key] = value

    return mutate


def _add_entry(trace: Trace) -> None:
    trace["candidates"][0]["cases"][0]["entries"].append(_entries(1)[1])


def _drop_case(trace: Trace) -> None:
    del trace["candidates"][0]["cases"][1]


def _swap_cases(trace: Trace) -> None:
    cases = trace["candidates"][0]["cases"]
    cases[0], cases[1] = cases[1], cases[0]


def _relabel(trace: Trace) -> None:
    trace["candidates"][0]["candidate"] = "other"


def _reschema(trace: Trace) -> None:
    trace["schema"] = "screamingface.report-trace.v2"


def _drop_key(trace: Trace) -> None:
    del trace["candidates"][0]["cases"][0]["entries"][0]["status"]


def _kind(trace: Trace) -> None:
    trace["candidates"][0]["cases"][0]["entries"][1]["kind"] = "reduce"


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (_set_entry(0, "status", "failed"), f"{_CASE}.entries[0].status"),
        (_set_entry(1, "value", "41"), f"{_CASE}.entries[1].value"),
        (_add_entry, f"{_CASE}.entries"),
        (_drop_case, "candidates[0].cases"),
        (_swap_cases, f"{_CASE}.case_id|candidates[0].cases[1].case_id"),
        (_relabel, "candidates[0].candidate"),
        (_reschema, "schema"),
        (_drop_key, f"{_CASE}.entries[0]"),
        (_kind, f"{_CASE}.entries[1].kind"),
    ],
    ids=[
        "model_call.status",
        "extract.value",
        "extra entry",
        "missing case",
        "reordered case",
        "another candidate label",
        "another schema",
        "missing key",
        "another entry kind",
    ],
)
def test_any_other_difference_is_drift(mutate: Callable[[Trace], None], path: str) -> None:
    # `path` joins the expected paths with `|`: a swap of two Cases moves both.
    replay = _trace()
    mutate(replay)

    assert trace_drift(_trace(), replay) == tuple(path.split("|"))


def test_a_candidate_count_difference_is_drift() -> None:
    replay = _trace()
    replay["candidates"].append(copy.deepcopy(replay["candidates"][0]))

    assert trace_drift(_trace(), replay) == ("candidates",)
