"""Attribute captured terminal calls to stable Candidate operation ids (OME-843).

Think of it as matching two ledgers after the fact. During one Candidate
invocation the connector records every terminal model call with its route
identity (:mod:`screamingface_engine.operation_calls`); this module reads the SAME
identities out of the candidate expression's named sources and joins the two —
so a Fusion case artifact can say which member produced which answer.

Stages, in execution order:

1. Parse the candidate expression the adapter already holds and select its
   named ``model_N`` / ``synthesis_N`` / ``judge_N`` / ``writer_N`` sources — the
   identical naming rule the Client's operation projection uses
   (``operation_id = "op_" + binding``), so both sides agree with no protocol change.
2. Fingerprint each source as (path, sorted params). Two members on the same
   model route with different params (e.g. temperature) stay distinct.
3. Join recorded calls to bindings by fingerprint. A fingerprint claimed by ONE
   binding takes its last (terminal) call. A fingerprint claimed by SEVERAL
   bindings shares identical recorded outputs only when every claimant is required.
   If any claimant belongs to an optional subtree, the observations cannot prove
   which operation answered; output and finish reason stay null for every claimant.
   Never make a positional guess.
   Combine evidence (OME-1289) follows the stricter rule: it is attributed only
   when ONE binding claims the fingerprint, never when several do, even if their
   recorded outputs are identical.
   The abstain mark (OME-1289) reads the final operation's evidence.

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
from url4.core.nodes import Expression, RelExpr, Source, Text, walk
from url4.core.parser import build

# INVARIANT: kept in lock-step with the Client's operation projection, where
# `operation_id = "op_" + binding` and bindings are model_N / synthesis_N / judge_N / writer_N
# (OME-1289 E4a). `tests/unit/data/combine_contract/binding_names.json` pins this pattern in
# both packages.
_BINDING = re.compile(r"^(?:model|synthesis|judge|writer)_\d+$")

# The root intent that names exactly one source (`$synthesis_1`), nothing else around it.
_FINAL_REFERENCE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")

type _Fingerprint = tuple[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True, slots=True)
class _OperationBinding:
    binding: str
    fingerprint: _Fingerprint | None
    optional: bool = False


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
    optional = {
        binding.fingerprint
        for binding in bindings
        if binding.optional and binding.fingerprint is not None
    }
    operations = [_attributed(binding, by_fingerprint, claims, optional) for binding in bindings]
    if len(bindings) == 1 and bindings[0].fingerprint is None:
        return None
    return operations


def final_operation_abstained(
    expression: str, operations: Sequence[OperationOutput] | None
) -> bool:
    """True when the expression's result IS one attributed combine operation that abstained.

    The final node is the source the root intent names when that intent is exactly `$name`;
    its evidence is the attributed `op_<name>` operation's `combine` (last call, one claimant).
    Prose intents, other roots and unattributed names are never marked (OME-1289, erd section 9).
    """

    if operations is None or (name := _final_reference(expression)) is None:
        return False
    matches = [op for op in operations if op.operation_id == f"op_{name}"]
    return (
        len(matches) == 1
        and matches[0].combine is not None
        and matches[0].combine.result.status == "abstain"
    )


def _final_reference(expression: str) -> str | None:
    """The `name` of a root intent that is exactly `$name`; None for any other root."""

    try:
        node = build(expression)
    except ParseError:
        return None
    if not isinstance(node, Expression) or not isinstance(node.intent, Text):
        return None
    matched = _FINAL_REFERENCE.fullmatch(node.intent.value)
    return None if matched is None else matched.group(1)


def _attributed(
    binding: _OperationBinding,
    by_fingerprint: dict[_Fingerprint, list[OperationCall]],
    claims: dict[_Fingerprint, int],
    optional: set[_Fingerprint],
) -> OperationOutput:
    output: str | None = None
    finish_reason: str | None = None
    accounting = None
    combine = None
    matched = [] if binding.fingerprint is None else by_fingerprint.get(binding.fingerprint, [])
    if matched and claims.get(binding.fingerprint or ("", ()), 0) == 1:
        # One claimant: every matched call IS this operation; the last one is terminal
        # (a corrective re-invocation repeats the operation, and only its final answer
        # is the one the Candidate used).
        output, finish_reason = matched[-1].output, matched[-1].finish_reason
        # A combine call's evidence follows the same last-call rule, and only a ONE-claimant
        # fingerprint may carry it (the ambiguous branch below never invents evidence).
        combine = matched[-1].combine
        if all(call.accounting is not None for call in matched):
            accounting = combine_operation_accounting(
                [call.accounting for call in matched if call.accounting is not None]
            )
    # WHY: an optional claimant may have failed without recording a terminal
    # call. Identical answers, even from repeated calls, do not prove it answered.
    elif matched and binding.fingerprint not in optional:
        distinct = {(call.output, call.finish_reason) for call in matched}
        if len(distinct) == 1:
            output, finish_reason = next(iter(distinct))
    return OperationOutput(
        operation_id=f"op_{binding.binding}",
        output=output,
        finish_reason=finish_reason,
        accounting=accounting,
        combine=combine,
    )


def _operation_bindings(expression: str) -> tuple[_OperationBinding, ...]:
    try:
        node = build(expression)
    except ParseError:
        return ()
    if not isinstance(node, Expression):
        return ()
    optional = _optional_bindings(node)
    selected: list[_OperationBinding] = []
    # Quorum panels nest complete member Recipes. Their model bindings still
    # own outputs and accounting, even though they are no longer root sources.
    for source in (nested for root in node.sources for nested in _panel_sources(root)):
        if not isinstance(source, Source) or source.name is None:
            continue
        if not _BINDING.match(source.name):
            continue
        selected.append(
            _OperationBinding(source.name, _fingerprint(source.value), source.name in optional)
        )
    return tuple(selected)


def _optional_bindings(expression: Expression) -> set[str]:
    # INVARIANT: a complete optional Recipe can fail after any of its internal
    # operations; all descendant bindings participate in the same uncertainty.
    return {
        child.name
        for node in walk(expression)
        if isinstance(node, Source) and any(key == "optional" for key, _ in node.annotations)
        for child in walk(node)
        if isinstance(child, Source) and child.name is not None
    }


def _panel_sources(value: object) -> tuple[Source, ...]:
    if not isinstance(value, Source):
        return ()
    if (
        value.name is not None
        and re.fullmatch(r"panel_\d+", value.name)
        and isinstance(value.value, Expression)
    ):
        return tuple(node for node in walk(value.value) if isinstance(node, Source))
    # Other nested bindings keep their legacy opaque attribution semantics.
    return (value,)


def _fingerprint(value: object) -> _Fingerprint | None:
    # A binding whose value is not a direct model call (a nested Recipe, inert text)
    # has no request identity to match; its entry stays null rather than guessed.
    if not isinstance(value, RelExpr):
        return None
    params = tuple(sorted((name, item) for name, item in value.params if isinstance(item, str)))
    return (value.path, params)


__all__ = ["attribute_operation_outputs", "final_operation_abstained"]
