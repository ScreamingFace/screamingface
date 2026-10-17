"""The vote gate: one number, one comparison, one branch (E4b part 5; gate-decision PRD §2).

FEATURE: a vote keeps its majority answer only when a computed number passes the threshold that the
recipe wrote; otherwise the fallback gives the answer (ans:Q1, ans:Q2, ans:Q3).
INVARIANT: pure functions of their arguments (C9): no I/O, no clock, no model call. The number is
computed, never asked of a model.
INVARIANT (FB-I1): only ``fallback_label`` and ``fallback_text`` read a fallback reply, and the
endpoint calls them only on the fallback branch.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from types import MappingProxyType

from screamingface_engine.combine.ports import (
    GateCmp,
    JudgeReading,
    Selection,
    SpecInvalid,
    judge_reply,
    parse_label,
)
from screamingface_engine.combine.spec import FALLBACK_JUDGE, FALLBACK_WRITER, GateSpec

_FALLBACK_KEYS: Mapping[str, str] = MappingProxyType(
    {"judge": FALLBACK_JUDGE, "writer": FALLBACK_WRITER}
)
_COMPARE: Mapping[str, Callable[[float, float], bool]] = MappingProxyType(
    {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}
)


def observed_number(
    gate: GateSpec,
    selection: Selection,
    recorded: Mapping[str, Mapping[str, float | None]],
    members: Sequence[str],
) -> float | None:
    """The number the gate compares (P11, P12).

    ``agreement``: the select step's agreement. ``chosen:<n>``: the chosen member's recorded value
    of ``<n>``; None when the step chose no member (it built the answer). ``mean:<n>``:
    ``math.fsum`` of the non-None values of ``<n>`` over ``members`` (any status), divided by their
    count; None when no member has a value. Past the float range the mean is exact (E6).
    """
    source, _, name = gate.observe.partition(":")
    if source == "agreement":
        return selection.agreement
    if source == "chosen":
        return recorded[selection.chosen[0]][name] if selection.chosen else None
    values = [number for member in members if (number := recorded[member][name]) is not None]
    return _mean(values)


def _mean(values: Sequence[float]) -> float | None:
    """``math.fsum`` of ``values`` over their count; None when there are none."""
    if not values:
        return None
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        # WHY Fraction: the sum of finite values can leave the float range, but their mean cannot;
        # the exact rational mean rounds to a finite float.
        return float(sum(map(Fraction, values), Fraction(0)) / len(values))


def passes(observed: float | None, cmp: GateCmp, threshold: float) -> bool:
    """``observed cmp threshold``; False when the number is missing (P10)."""
    return observed is not None and bool(_COMPARE[cmp](observed, threshold))


def fallback_label(signals: Mapping[str, str], kept: Sequence[str]) -> JudgeReading:
    """The label reading of the ``fallback_judge`` reply over ``kept`` (GD-E6).

    ``kept``: the present members that the step did not exclude, in spec order.
    """
    raw = judge_reply(signals, "the gate fallback", key=FALLBACK_JUDGE)
    return JudgeReading(raw, "label", parse_label(raw, kept))


def fallback_text(signals: Mapping[str, str]) -> str:
    """The ``fallback_writer`` reply, verbatim."""
    text = signals.get(FALLBACK_WRITER)
    if text is None:
        raise SpecInvalid(f"the gate fallback needs the {FALLBACK_WRITER} signal")
    return text


def check_fallback_signals(gate: GateSpec | None, signals: Mapping[str, str]) -> None:
    """CX-I1: a context holds a fallback key only when the spec gate names that fallback."""
    named = None if gate is None else _FALLBACK_KEYS.get(gate.otherwise)
    if any(key in signals and key != named for key in _FALLBACK_KEYS.values()):
        raise SpecInvalid("a fallback signal needs a gate that names it")


__all__ = [
    "check_fallback_signals",
    "fallback_label",
    "fallback_text",
    "observed_number",
    "passes",
]
