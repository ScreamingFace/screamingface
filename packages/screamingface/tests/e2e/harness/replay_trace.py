"""The RT-4 rule: a cached replay's trace differs from the live run's only in model-call accounting.

INVARIANT: pure; reads two screamingface.report-trace.v1 documents; never raises on drift, it lists
it.

Mental model: walk both documents level by level (candidates, Cases, entries, keys) and name the
first place of each difference. A level whose shape differs (a count, a label, a Case id, a kind,
a key set) is reported at that level and not walked deeper, because the deeper paths would not
line up.
Worked example: a replay that served ``op_model_2`` from the cache has another ``cache`` and no
``cost_usd`` there. That is allowed. A replay whose second extract read "41" instead of "42" is
reported as ``candidates[0].cases[3].entries[2].value``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

MODEL_CALL_ACCOUNTING: Final = ("cache", "cost_usd", "latency_ms", "tokens_in", "tokens_out")


def trace_drift(live: Mapping[str, Any], replay: Mapping[str, Any]) -> tuple[str, ...]:
    """Every path where the two traces differ outside MODEL_CALL_ACCOUNTING, in document order."""
    drift = ["schema"] if live.get("schema") != replay.get("schema") else []
    drift += _candidates_drift(live.get("candidates", ()), replay.get("candidates", ()))
    return tuple(drift)


def _candidates_drift(live: Sequence[Any], replay: Sequence[Any]) -> list[str]:
    if len(live) != len(replay):
        return ["candidates"]
    drift: list[str] = []
    for index, (left, right) in enumerate(zip(live, replay, strict=True)):
        base = f"candidates[{index}]"
        if left.get("candidate") != right.get("candidate"):
            drift.append(f"{base}.candidate")
        drift += _cases_drift(left.get("cases", ()), right.get("cases", ()), base)
    return drift


def _cases_drift(live: Sequence[Any], replay: Sequence[Any], base: str) -> list[str]:
    if len(live) != len(replay):
        return [f"{base}.cases"]
    drift: list[str] = []
    for index, (left, right) in enumerate(zip(live, replay, strict=True)):
        path = f"{base}.cases[{index}]"
        if left.get("case_id") != right.get("case_id"):
            drift.append(f"{path}.case_id")
        else:
            drift += _entries_drift(left.get("entries", ()), right.get("entries", ()), path)
    return drift


def _entries_drift(live: Sequence[Any], replay: Sequence[Any], base: str) -> list[str]:
    if len(live) != len(replay):
        return [f"{base}.entries"]
    drift: list[str] = []
    for index, (left, right) in enumerate(zip(live, replay, strict=True)):
        drift += _entry_drift(left, right, f"{base}.entries[{index}]")
    return drift


def _entry_drift(live: Mapping[str, Any], replay: Mapping[str, Any], path: str) -> list[str]:
    if live.get("kind") != replay.get("kind"):
        return [f"{path}.kind"]
    if set(live) != set(replay):
        return [path]
    free = MODEL_CALL_ACCOUNTING if live.get("kind") == "model_call" else ()
    return [f"{path}.{key}" for key in live if key not in free and live[key] != replay[key]]
