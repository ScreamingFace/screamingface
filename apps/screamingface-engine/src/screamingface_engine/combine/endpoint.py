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
INVARIANT: only a ``CombineError`` is a declared failure. A plugin bug stays loud. A step that
finds no answer (no usable member, or a reduce or select step raising ``NoVotes``) is not a
failure: it returns the empty text and evidence with ``result.status == "abstain"``.
INVARIANT: a failure message names ids, counts and limits -- never member text or arg values.
WHY no ``record_model_outcome``: the step is not a model call, so the Candidate's terminal finish
reason stays the members' common reason; the operation's own finish reason is ``stop``.
"""

from __future__ import annotations

import contextlib
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
    AnswerRecord,
    CombineEvidence,
    FieldReadingRecord,
    JudgeReadingRecord,
    ResultRecord,
    SignalRecord,
    TallyRowRecord,
)
from screamingface_engine.combine.ports import (
    ACCOUNTING_SIGNALS,
    FIELD_SIGNAL_PREFIX,
    READING_TO_ANSWER,
    AbstainReason,
    AccountingReader,
    Answer,
    CombineError,
    CombineInput,
    EvidenceKind,
    Extractor,
    InputTooLarge,
    Normalizer,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    ReadingStatus,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    SignalRead,
    SpecInvalid,
    Stage,
    StageResult,
    answer_status,
    canonical_decimal,
    field_signal_value,
    is_signal_key,
    utf8_exceeds,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.combine.spec import (
    MAX_MEMBERS,
    MAX_WEIGHT,
    REDUCER_RULES,
    CombineContext,
    CombineSpec,
    SignalWeights,
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
    signal: SignalRead | None = None

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
    registry: OperatorRegistry,
    params: Mapping[str, str],
    context: str,
    intent: str,
    *,
    accounting: AccountingReader | None = None,
) -> CombineOutcome:
    """Run one combine spec. Raises ``CombineError`` (a declared code) on any declared failure.

    Logs the one documented line (FW-17) for a success and for each ``CombineError``.
    """
    trace = _Trace()
    try:
        outcome = _combine(registry, params, context, intent, trace, accounting)
    except CombineError as exc:
        trace.log(exc.code)
        raise
    except Exception:
        # A plugin bug: log the one line, then let it travel unchanged (it is not a declared code).
        trace.log("internal_error")
        raise
    result = outcome.evidence.result
    trace.log("ok" if result.status == "answered" else f"abstain_{result.reason}")
    return outcome


def _combine(
    registry: OperatorRegistry,
    params: Mapping[str, str],
    context_text: str,
    intent: str,
    trace: _Trace,
    accounting: AccountingReader | None,
) -> CombineOutcome:
    trace.binding = _binding(params)
    _check_sizes(intent, context_text)
    spec = parse_spec(intent)
    trace.reducer, trace.members = spec.reducer, str(len(spec.members))
    if len(spec.members) > MAX_MEMBERS:
        raise InputTooLarge(f"a combine call takes at most {MAX_MEMBERS} members")
    plan = _plan(spec, registry)
    context = parse_context(
        context_text,
        spec.members,
        sources_expected=plan.signal is not None and plan.signal.key in ACCOUNTING_SIGNALS,
    )
    values = _signal_values(plan.signal, spec, context, accounting)
    combine_input = _read_members(spec, plan, context, values)
    trace.voters = str(len(combine_input.voters))
    reduction, selection = _reduce_select(plan, combine_input)
    if isinstance(selection, str):  # an AbstainReason
        return _abstain(spec, plan, combine_input, reduction, selection)
    output = _output(selection, plan.select.op_id, context)
    trace.agreement = "-" if selection.agreement is None else str(selection.agreement)
    trace.tie = "true" if selection.tie else "false"
    result = _result(selection, REDUCER_RULES[spec.reducer].kind, output, combine_input)
    evidence = _evidence(spec, plan, combine_input, reduction, selection, result)
    return CombineOutcome(output, evidence)


def _finite_or_none(value: object) -> float | None:
    """A number from the accounting reader, kept only when it is a finite int or float."""
    number: float | None = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        with contextlib.suppress(OverflowError):  # an int too large for a float
            number = float(value)
    return number if number is not None and math.isfinite(number) else None


def _signal_values(
    read: SignalRead | None,
    spec: CombineSpec,
    context: CombineContext,
    accounting: AccountingReader | None,
) -> dict[str, float | None] | None:
    """Each member's number for the one signal the spec reads; None when it reads none."""
    if read is None:
        return None
    if read.key in ACCOUNTING_SIGNALS:
        # WHY the reader is a port: the core does no I/O and has no recorder; the adapter knows
        # what each source call cost. Without a reader every member's number is unknown.
        sources = context.sources
        assert sources is not None  # parse_context required it for an accounting key
        looked = {} if accounting is None else accounting(sources)
        return {m: _finite_or_none(looked.get(m, {}).get(read.key)) for m in spec.members}
    path = read.key[len(FIELD_SIGNAL_PREFIX) :]
    return {
        member: None
        if utf8_exceeds(context.outputs[member], MAX_OUTPUT_READ_BYTES)
        else field_signal_value(context.outputs[member], path)
        for member in spec.members
    }


def _reduce_select(
    plan: _Plan, combine_input: CombineInput
) -> tuple[Reduction | None, Selection | AbstainReason]:
    """Run reduce, then select. Returns the reduction (None when reduce did not finish) and the
    selection, or the reason to abstain. Only a reduce or select step may abstain."""
    reduction: Reduction | None = None
    outcome: Selection | AbstainReason = "no_votes"
    try:
        if combine_input.voters:
            reduction = plan.reduce.run(combine_input, plan.reduce.args)
            _check_tally(reduction, combine_input.members, plan.reduce.op_id)
            outcome = plan.select.run(reduction, combine_input, plan.select.args)
    except NoVotes as exc:
        outcome = exc.reason
    return reduction, outcome


def _abstain(
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    reduction: Reduction | None,
    reason: AbstainReason,
) -> CombineOutcome:
    """The normal output of a step that finds no answer: the empty text and an abstain result."""
    result = ResultRecord(member_id=None, value=None, status="abstain", reason=reason)
    evidence = _evidence(spec, plan, combine_input, reduction, None, result)
    return CombineOutcome("", evidence)


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
    bound_reduce = cast("_Step[ReduceOp]", _bind(reduce, spec.reduce))
    return _Plan(
        extract=cast("_Step[Extractor] | None", _bind(extract, spec.extract)),
        normalize=cast("_Step[Normalizer] | None", _bind(normalize, spec.normalize)),
        reduce=bound_reduce,
        select=cast("_Step[SelectOp]", _bind(select, spec.select)),
        signal=_signal_read(spec, reduce, bound_reduce),
    )


def _signal_read(
    spec: CombineSpec, reduce: OperatorDescriptor | None, bound: _Step[ReduceOp]
) -> SignalRead | None:
    """The one signal the spec reads: from ``weights``, or from the reduce step's args (F6)."""
    from_weights = (
        SignalRead(spec.weights.signal) if isinstance(spec.weights, SignalWeights) else None
    )
    hook = None if reduce is None else reduce.signal_read
    from_reduce = None if hook is None else hook(bound.args)
    if from_reduce is not None:
        if not is_signal_key(from_reduce.key):
            raise SpecInvalid(f"{bound.op_id} reads an unknown signal")
        if from_reduce.order not in (None, "max", "min"):
            raise RuntimeError(f"{bound.op_id} returned an invalid signal read")  # a plugin bug
    if from_weights is not None and from_reduce is not None:
        raise SpecInvalid("a combine step reads at most one signal")
    return from_reduce if from_weights is None else from_weights


def _read_members(
    spec: CombineSpec,
    plan: _Plan,
    context: CombineContext,
    values: Mapping[str, float | None] | None,
) -> CombineInput:
    """One ``Answer`` per member in spec order; ``values`` is the signal the spec reads (I-S3)."""
    fixed = {} if not isinstance(spec.weights, dict) else spec.weights
    answers = tuple(
        _answer(
            member,
            context.outputs[member],
            plan,
            MappingProxyType({})
            if values is None or plan.signal is None
            else MappingProxyType({plan.signal.key: values[member]}),
            _weight(spec, fixed, member, None if values is None else values[member]),
        )
        for member in spec.members
    )
    return CombineInput(answers=answers, outputs=context.outputs, signals=context.signals)


def _weight(
    spec: CombineSpec, fixed: Mapping[str, float], member: str, signal: float | None
) -> Decimal | None:
    """A fixed weight as authored; a signal weight only when it is a usable positive number."""
    if isinstance(spec.weights, SignalWeights):
        usable = signal is not None and 0 < signal <= MAX_WEIGHT
        return Decimal(str(signal)) if usable else None
    return Decimal(str(fixed[member])) if member in fixed else None


def _answer(
    member_id: str,
    text: str,
    plan: _Plan,
    signals: Mapping[str, float | None],
    weight: Decimal | None,
) -> Answer:
    status, raw, value = _stages(text, plan)
    answer_state, reason = answer_status(status)
    if plan.extract is not None and answer_state == "answered" and value is None:
        # A checked stage result cannot get here; the guard keeps I-A1 true if a stage changes.
        raise RuntimeError(f"{plan.extract.op_id} returned an answered member without a value")
    return Answer(member_id, raw, value, answer_state, reason, signals, weight)


def _stages(text: str, plan: _Plan) -> tuple[ReadingStatus, str | None, str | None]:
    """The (status, raw, value) of one member text after extract, then normalize."""
    if utf8_exceeds(text, MAX_OUTPUT_READ_BYTES):
        return "too_large", None, None
    if plan.extract is None:
        return "voted", None, None
    return _extract_then_normalize(text, plan.extract, plan.normalize)


def _checked(result: StageResult, op_id: str) -> StageResult:
    """A plugin's stage result, verified: a duck-typed object is a plugin bug, not a vote."""
    status, value = getattr(result, "status", None), getattr(result, "value", None)
    if (
        not isinstance(status, str)
        or status not in READING_TO_ANSWER
        or not (value is None or isinstance(value, str))
        or (status == "voted") != (value is not None)
    ):
        raise RuntimeError(f"{op_id} returned an invalid stage result")
    return result


def _extract_then_normalize(
    text: str, extract: _Step[Extractor], normalize: _Step[Normalizer] | None
) -> tuple[ReadingStatus, str | None, str | None]:
    raw = _checked(extract.run(text, extract.args), extract.op_id)
    if raw.value is None or normalize is None:
        return raw.status, raw.value, raw.value
    normalized = _checked(normalize.run(raw.value, normalize.args), normalize.op_id)
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


def _result(
    selection: Selection, kind: EvidenceKind, output: str, combine_input: CombineInput
) -> ResultRecord:
    """The computed answer: the chosen member's value, or (built) the output for answer and
    projection kinds. A selection kind keeps no value (I-E1: it would carry member text)."""
    if selection.output is None:
        winner = next(a for a in combine_input.answers if a.member_id == selection.chosen[0])
        return ResultRecord(
            member_id=winner.member_id, value=winner.value, status="answered", reason=None
        )
    value = output if kind in ("answer", "projection") else None
    return ResultRecord(member_id=None, value=value, status="answered", reason=None)


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
    reduction: Reduction | None,
    selection: Selection | None,
    result: ResultRecord,
) -> CombineEvidence:
    # An abstain has no selection, and none or only part of a reduction (a select step may abstain).
    reduction = Reduction() if reduction is None else reduction
    scores = reduction.scores or {}
    statistic = reduction.statistic
    return CombineEvidence(
        kind=REDUCER_RULES[spec.reducer].kind,
        reducer=spec.reducer,
        operators=list(plan.operators),
        members=[_member_record(answer, scores) for answer in combine_input.answers],
        tally=_tally_records(reduction),
        judge=_judge_record(reduction),
        fields=_field_records(reduction, plan.reduce.op_id),
        chosen=[] if selection is None else list(selection.chosen),
        built=selection is not None and selection.output is not None,
        agreement=(
            None
            if selection is None or selection.agreement is None
            else _finite(selection.agreement)
        ),
        tie=selection is not None and selection.tie,
        median=None if statistic is None else canonical_decimal(statistic),
        presentation_order="author" if "judge" in combine_input.signals else None,
        separator_collision=reduction.separator_collision,
        signal=None
        if plan.signal is None
        else SignalRecord(key=plan.signal.key, order=plan.signal.order),
        result=result,
        dropped=sum(answer.status == "fail" for answer in combine_input.answers),
        finish_reason="stop",
    )


def _member_record(answer: Answer, scores: Mapping[str, Decimal]) -> AnswerRecord:
    return AnswerRecord(
        member_id=answer.member_id,
        raw=answer.raw,
        value=answer.value,
        status=answer.status,
        reason=answer.reason,
        signals=dict(answer.signals),
        weight=None if answer.weight is None else _finite(answer.weight),
        score=_finite(scores[answer.member_id]) if answer.member_id in scores else None,
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
