"""The pure core of the combine call: run one spec over member outputs (OME-1289 E4a).

FEATURE: deterministic combine -- pick or build the answer from the members' own texts with pure
functions, and never call a model.
STORY: as the url4 route adapter (``world/combine.py``), I hand over one call's params, context
(the member outputs) and intent (the spec) and get back one member's text byte for byte, or a text
built only by the spec's operators, plus the ``CombineEvidence`` of what happened.

One call runs: read the members (extract, then normalize), reduce, select, check.

INVARIANT: this module imports no ``url4`` module -- the adapter owns the route, the
``ResolutionError`` mapping and the task-local record (a side effect), so the core stays pure.
INVARIANT: pure CPU work -- no HTTP client, no clock, no cache, no module state. Order always
comes from ``spec.members``; nothing iterates a dict or set to decide an output.
INVARIANT: only a ``CombineError`` is a declared failure. A plugin bug stays loud.
INVARIANT: a failure message names ids, counts and limits -- never member text or arg values.
WHY no ``record_model_outcome``: the step is not a model call, so the Candidate's terminal finish
reason stays the members' common reason; the operation's own finish reason is ``stop``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

from pydantic import ValidationError

from screamingface_engine.combine.evidence import (
    CombineEvidence,
    FieldReadingRecord,
    JudgeReadingRecord,
    MemberReadingRecord,
    TallyRowRecord,
)
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    Extractor,
    InputTooLarge,
    MemberReading,
    Normalizer,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    ReadingStatus,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    SpecInvalid,
    Stage,
    canonical_decimal,
    utf8_exceeds,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.combine.spec import (
    MAX_MEMBERS,
    REDUCER_RULES,
    CombineContext,
    CombineSpec,
    StepSpec,
    parse_context,
    parse_spec,
)

COMBINE_ROUTE = "/ensemble/combine/v1"
MAX_SPEC_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_READ_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
_BINDING = re.compile(r"synthesis_\d+")  # same \d+ as benchmarks/operation_outputs.py

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Step[F]:
    """One resolved spec step: the pinned id, the operator to run, and its checked args."""

    op_id: str
    run: F
    args: OpArgs


@dataclass(frozen=True, slots=True)
class _Plan:
    """The four resolved stages of one call; ``extract`` and ``normalize`` may be absent."""

    extract: _Step[Extractor] | None
    normalize: _Step[Normalizer] | None
    reduce: _Step[ReduceOp]
    select: _Step[SelectOp]

    @property
    def operators(self) -> tuple[str, ...]:
        """The pinned ids in stage order; absent steps are skipped."""
        steps = (self.extract, self.normalize, self.reduce, self.select)
        return tuple(step.op_id for step in steps if step is not None)


@dataclass(slots=True)
class _Trace:
    """The fields of the one log line per call; ``-`` until known."""

    binding: str = "-"
    reducer: str = "-"
    voters: str = "-"
    members: str = "-"
    agreement: str = "-"
    tie: str = "-"

    def log(self, outcome: str) -> None:
        logger.info(
            "combine binding=%s reducer=%s voters=%s/%s agreement=%s tie=%s outcome=%s",
            self.binding,
            self.reducer,
            self.voters,
            self.members,
            self.agreement,
            self.tie,
            outcome,
        )


@dataclass(frozen=True, slots=True)
class CombineOutcome:
    """What one successful combine call produced."""

    output: str
    evidence: CombineEvidence


def run_combine(
    registry: OperatorRegistry, params: Mapping[str, str], context: str, intent: str
) -> CombineOutcome:
    """Run one combine spec. Raises ``CombineError`` (a declared code) on any declared failure.

    Logs the one documented line (FW-17) for a success and for each ``CombineError``.
    """
    trace = _Trace()
    try:
        outcome = _combine(registry, params, context, intent, trace)
    except CombineError as exc:
        trace.log(exc.code)
        raise
    except Exception:
        # A plugin bug: log the one line, then let it travel unchanged (it is not a declared code).
        trace.log("internal_error")
        raise
    trace.log("ok")
    return outcome


def _combine(
    registry: OperatorRegistry,
    params: Mapping[str, str],
    context_text: str,
    intent: str,
    trace: _Trace,
) -> CombineOutcome:
    trace.binding = _binding(params)
    _check_sizes(intent, context_text)
    spec = parse_spec(intent)
    trace.reducer, trace.members = spec.reducer, str(len(spec.members))
    if len(spec.members) > MAX_MEMBERS:
        raise InputTooLarge(f"a combine call takes at most {MAX_MEMBERS} members")
    plan = _plan(spec, registry)
    context = parse_context(context_text, spec.members)
    combine_input = _read_members(spec, plan, context)
    trace.voters = str(len(combine_input.voters))
    if not combine_input.voters:
        raise NoVotes(f"no member gave a usable value ({len(spec.members)} members)")
    reduction = plan.reduce.run(combine_input, plan.reduce.args)
    _check_tally(reduction, combine_input.members, plan.reduce.op_id)
    selection = plan.select.run(reduction, combine_input, plan.select.args)
    output = _output(selection, plan.select.op_id, context)
    trace.agreement = "-" if selection.agreement is None else str(selection.agreement)
    trace.tie = "true" if selection.tie else "false"
    evidence = _evidence(spec, plan, combine_input, reduction, selection)
    return CombineOutcome(output, evidence)


def _binding(params: Mapping[str, str]) -> str:
    binding = params.get("binding")
    if set(params) != {"binding"} or binding is None or _BINDING.fullmatch(binding) is None:
        raise SpecInvalid("a combine call takes exactly one param: binding=synthesis_N")
    return binding


def _check_sizes(intent: str, context: str) -> None:
    if utf8_exceeds(intent, MAX_SPEC_BYTES):
        raise InputTooLarge("the combine spec exceeds 64 KiB")
    # WHY before any JSON parse: an oversize context must cost one length check, not a decode.
    if utf8_exceeds(context, MAX_CONTEXT_BYTES):
        raise InputTooLarge("the combine context exceeds 64 MiB")


def _resolve(
    registry: OperatorRegistry, step: StepSpec | None, stage: Stage
) -> OperatorDescriptor | None:
    return None if step is None else registry.resolve(step.op, stage)


def _bind(descriptor: OperatorDescriptor | None, step: StepSpec | None) -> _Step[Any] | None:
    if descriptor is None or step is None:
        return None
    try:
        descriptor.check_args(step.args)
    except SpecInvalid as exc:
        raise SpecInvalid(f"{descriptor.id} args are invalid: {exc}") from exc
    return _Step(descriptor.id, descriptor.run, MappingProxyType(dict(step.args)))


def _plan(spec: CombineSpec, registry: OperatorRegistry) -> _Plan:
    # WHY resolve ALL four steps before checking any args: an unknown operator is the more basic
    # failure, so it wins over bad args of an earlier step. Stage order: extract, normalize,
    # reduce, select.
    extract = _resolve(registry, spec.extract, "extract")
    normalize = _resolve(registry, spec.normalize, "normalize")
    reduce = _resolve(registry, spec.reduce, "reduce")
    select = _resolve(registry, spec.select, "select")
    return _Plan(
        extract=cast("_Step[Extractor] | None", _bind(extract, spec.extract)),
        normalize=cast("_Step[Normalizer] | None", _bind(normalize, spec.normalize)),
        reduce=cast("_Step[ReduceOp]", _bind(reduce, spec.reduce)),
        select=cast("_Step[SelectOp]", _bind(select, spec.select)),
    )


def _read_members(spec: CombineSpec, plan: _Plan, context: CombineContext) -> CombineInput:
    weights = {} if spec.weights is None else {m: Decimal(str(w)) for m, w in spec.weights.items()}
    readings = tuple(
        _reading(member, context.outputs[member], plan, weights.get(member))
        for member in spec.members
    )
    return CombineInput(readings=readings, outputs=context.outputs, signals=context.signals)


def _reading(member: str, text: str, plan: _Plan, weight: Decimal | None) -> MemberReading:
    status, raw, value = _stages(text, plan)
    return MemberReading(member, raw, value, status, weight)


def _stages(text: str, plan: _Plan) -> tuple[ReadingStatus, str | None, str | None]:
    """The (status, raw, value) of one member text after extract, then normalize."""
    if utf8_exceeds(text, MAX_OUTPUT_READ_BYTES):
        return "too_large", None, None
    if plan.extract is None:
        return "voted", None, None
    return _extract_then_normalize(text, plan.extract, plan.normalize)


def _extract_then_normalize(
    text: str, extract: _Step[Extractor], normalize: _Step[Normalizer] | None
) -> tuple[ReadingStatus, str | None, str | None]:
    raw = extract.run(text, extract.args)
    if raw.value is None or normalize is None:
        return raw.status, raw.value, raw.value
    normalized = normalize.run(raw.value, normalize.args)
    return normalized.status, raw.value, normalized.value


def _output(selection: Selection, op_id: str, context: CombineContext) -> str:
    chosen = selection.chosen
    if (
        len(set(chosen)) != len(chosen)
        or any(member not in context.outputs for member in chosen)
        or (selection.output is None and len(chosen) != 1)
    ):
        raise RuntimeError(f"{op_id} returned an invalid selection")  # a plugin contract bug
    output = context.outputs[chosen[0]] if selection.output is None else selection.output
    if utf8_exceeds(output, MAX_RESULT_BYTES):
        raise InputTooLarge("the combine output exceeds 8 MiB")
    return output


def _check_tally(reduction: Reduction, members: tuple[str, ...], op_id: str) -> None:
    """Verify, never repair: a tally the plugin got wrong must not be hidden by a re-sort.

    Rows must run by score (high first, compared as Decimals), then by the author position of
    the first holder; holders must run in author order. A wrong tally means the evidence would
    contradict the answer, so it is a plugin bug, raised as a ``RuntimeError`` like `_output`.
    """
    if reduction.tally is None:
        return
    position = {member: index for index, member in enumerate(members)}
    try:
        keys = [(-row.score, position[row.holders[0]]) for row in reduction.tally]
        held = [[position[holder] for holder in row.holders] for row in reduction.tally]
    except (IndexError, KeyError) as exc:
        raise RuntimeError(f"{op_id} returned an invalid tally") from exc
    if keys != sorted(keys) or any(order != sorted(order) for order in held):
        raise RuntimeError(f"{op_id} returned an unsorted tally")


def _finite(value: Decimal | float) -> float:
    """A score or weight as a float; a value no float can hold cannot be recorded."""
    number = float(value)
    if not math.isfinite(number):
        raise SpecInvalid("a combine score is too large to record")
    return number


def _evidence(
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    reduction: Reduction,
    selection: Selection,
) -> CombineEvidence:
    scores = reduction.scores or {}
    statistic = reduction.statistic
    return CombineEvidence(
        kind=REDUCER_RULES[spec.reducer].kind,
        reducer=spec.reducer,
        operators=list(plan.operators),
        members=[_member_record(reading, scores) for reading in combine_input.readings],
        tally=_tally_records(reduction),
        judge=_judge_record(reduction),
        fields=_field_records(reduction, plan.reduce.op_id),
        chosen=list(selection.chosen),
        built=selection.output is not None,
        agreement=None if selection.agreement is None else _finite(selection.agreement),
        tie=selection.tie,
        median=None if statistic is None else canonical_decimal(statistic),
        presentation_order="author" if "judge" in combine_input.signals else None,
        separator_collision=reduction.separator_collision,
        finish_reason="stop",
    )


def _member_record(reading: MemberReading, scores: Mapping[str, Decimal]) -> MemberReadingRecord:
    return MemberReadingRecord(
        member=reading.member,
        raw=reading.raw,
        value=reading.value,
        status=reading.status,
        weight=None if reading.weight is None else _finite(reading.weight),
        score=_finite(scores[reading.member]) if reading.member in scores else None,
    )


def _tally_records(reduction: Reduction) -> list[TallyRowRecord] | None:
    if reduction.tally is None:
        return None
    return [
        TallyRowRecord(value=row.value, score=_finite(row.score), holders=list(row.holders))
        for row in reduction.tally
    ]


def _judge_record(reduction: Reduction) -> JudgeReadingRecord | None:
    judge = reduction.judge
    if judge is None:
        return None
    parsed = judge.parsed if isinstance(judge.parsed, str) else dict(judge.parsed)
    return JudgeReadingRecord(raw=judge.raw, returns=judge.returns, parsed=parsed)


def _field_records(reduction: Reduction, op_id: str) -> list[FieldReadingRecord] | None:
    if reduction.fields is None:
        return None
    try:
        return [
            FieldReadingRecord(
                field=reading.field,
                rule=reading.rule,
                values=dict(reading.values),  # type: ignore[arg-type]  # validated below
                result=reading.result,  # type: ignore[arg-type]
            )
            for reading in reduction.fields
        ]
    except ValidationError as exc:
        raise RuntimeError(f"{op_id} returned a non-JSON field reading") from exc


__all__ = [
    "COMBINE_ROUTE",
    "MAX_CONTEXT_BYTES",
    "MAX_MEMBERS",
    "MAX_OUTPUT_READ_BYTES",
    "MAX_RESULT_BYTES",
    "MAX_SPEC_BYTES",
    "CombineOutcome",
    "run_combine",
]
