"""Attribute captured terminal calls to stable Candidate operation ids (OME-843).

Think of it as matching two ledgers after the fact. During one Candidate
invocation the connector records every terminal model call with its route
identity (:mod:`screamingface_engine.operation_calls`); this module reads the SAME
identities out of the candidate expression's named sources and joins the two —
so a Fusion case artifact can say which member produced which answer.

Stages, in execution order:

1. Parse the candidate expression the adapter already holds and select its
   named ``model_N`` / ``synthesis_N`` sources — the identical naming rule the
   Client's operation projection uses (``operation_id = "op_" + binding``), so
   both sides agree with no protocol change.
2. Fingerprint each source as (path, sorted params). Two members on the same
   model route with different params (e.g. temperature) stay distinct.
3. Join recorded calls to bindings by fingerprint. A fingerprint claimed by ONE
   binding takes its last (terminal) call. A fingerprint claimed by SEVERAL
   bindings is genuinely ambiguous: identical recorded outputs attribute to
   each claimant (no information invented), anything else stays null — never a
   positional guess.

Worked example — members ``/alpha?temperature=0.0``, ``/beta`` and synthesis
``/alpha?temperature=0.5`` with calls [(alpha@0.0 → "A"), (beta → "B"),
(alpha@0.5 → "F")]: three distinct fingerprints, so op_model_1="A",
op_model_2="B", op_synthesis_1="F". Had both members been ``/alpha?temperature=0.0``
returning "A1" and "A2", both would be null — the Engine cannot know which was which.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.operation_accounting import combine_operation_accounting
from screamingface_engine.operation_calls import OperationCall
from url4.core.errors import ParseError
from url4.core.nodes import Expression, RelExpr, Source
from url4.core.parser import build

# INVARIANT: kept in lock-step with the Client's operation projection, where
# `operation_id = "op_" + binding` and bindings are model_N / synthesis_N.
_BINDING = re.compile(r"^(?:model|synthesis)_\d+$")

type _Fingerprint = tuple[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True, slots=True)
class _OperationBinding:
    binding: str
    fingerprint: _Fingerprint | None


def attribute_operation_outputs(
    expression: str,
    calls: Sequence[OperationCall],
) -> list[OperationOutput] | None:
    """Join recorded calls to the expression's named model operations."""

    bindings = _operation_bindings(expression)
    if not bindings:
        return None
    by_fingerprint: dict[_Fingerprint, list[OperationCall]] = {}
    for call in calls:
        by_fingerprint.setdefault((call.path, call.params), []).append(call)
    claims: dict[_Fingerprint, int] = {}
    for binding in bindings:
        if binding.fingerprint is not None:
            claims[binding.fingerprint] = claims.get(binding.fingerprint, 0) + 1
    return [_attributed(binding, by_fingerprint, claims) for binding in bindings]


def _attributed(
    binding: _OperationBinding,
    by_fingerprint: dict[_Fingerprint, list[OperationCall]],
    claims: dict[_Fingerprint, int],
) -> OperationOutput:
    output: str | None = None
    finish_reason: str | None = None
    accounting = None
    matched = [] if binding.fingerprint is None else by_fingerprint.get(binding.fingerprint, [])
    if matched and claims.get(binding.fingerprint or ("", ()), 0) == 1:
        # One claimant: every matched call IS this operation; the last one is terminal
        # (a corrective re-invocation repeats the operation, and only its final answer
        # is the one the Candidate used).
        output, finish_reason = matched[-1].output, matched[-1].finish_reason
        if all(call.accounting is not None for call in matched):
            accounting = combine_operation_accounting(
                [call.accounting for call in matched if call.accounting is not None]
            )
    elif matched:
        distinct = {(call.output, call.finish_reason) for call in matched}
        if len(distinct) == 1:
            output, finish_reason = next(iter(distinct))
    return OperationOutput(
        operation_id=f"op_{binding.binding}",
        output=output,
        finish_reason=finish_reason,
        accounting=accounting,
    )


def _operation_bindings(expression: str) -> tuple[_OperationBinding, ...]:
    try:
        node = build(expression)
    except ParseError:
        return ()
    if not isinstance(node, Expression):
        return ()
    selected: list[_OperationBinding] = []
    for source in node.sources:
        if not isinstance(source, Source) or source.name is None:
            continue
        if not _BINDING.match(source.name):
            continue
        selected.append(_OperationBinding(source.name, _fingerprint(source.value)))
    return tuple(selected)


def _fingerprint(value: object) -> _Fingerprint | None:
    # A binding whose value is not a direct model call (a nested Recipe, inert text)
    # has no request identity to match; its entry stays null rather than guessed.
    if not isinstance(value, RelExpr):
        return None
    params = tuple(sorted((name, item) for name, item in value.params if isinstance(item, str)))
    return (value.path, params)


__all__ = ["attribute_operation_outputs"]
