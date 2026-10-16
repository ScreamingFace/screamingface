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
finds no answer (no usable member, a reduce or select step raising ``NoVotes``, or a vote gate that
takes the abstain fallback: ``gate_not_met``, E4b part 5) is not a failure: it returns evidence
with ``result.status == "abstain"`` and the empty text. A select operator with ``envelope`` (Rank,
Filter) returns the empty envelope instead (E4b fix 2026-10-14).
INVARIANT (FB-I1, E4b part 5): only the fallback branch of a gate reads a ``fallback_*`` reply.
INVARIANT: a failure message names ids, counts and limits -- never member text or arg values.
WHY no ``record_model_outcome``: the step is not a model call, so the Candidate's terminal finish
reason stays the members' common reason; the operation's own finish reason is ``stop``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal, cast

from pydantic import JsonValue, ValidationError

from screamingface_engine.combine.evidence import (
    AnswerRecord,
    CombineEvidence,
    CutRecord,
    FieldReadingRecord,
    GateRecord,
    JudgeReadingRecord,
    ResultRecord,
    SignalRecord,
    TallyRowRecord,
)
from screamingface_engine.combine.gate import (
    check_fallback_signals,
    fallback_label,
    fallback_text,
    observed_number,
    passes,
)
from screamingface_engine.combine.logprob_forms import entropy_value, logprob_value
from screamingface_engine.combine.ports import (
    ACCOUNTING_SIGNALS,
    FIELD_SIGNAL_PREFIX,
    JUDGE_SIGNAL,
    MAX_OUTPUT_READ_BYTES,
    READING_TO_ANSWER,
    REPLY_ENTROPY_MEAN,
    REPLY_LOGPROB_SUM,
    REPLY_TOKENS,
    AbstainReason,
    AccountingReader,
    Answer,
    AnswerReason,
    CombineError,
    CombineInput,
    Cut,
    EvidenceKind,
    ExcludeReason,
    Extractor,
    InputTooLarge,
    MemberSources,
    Normalizer,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    ReadingStatus,
    RecordStatus,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    SignalRead,
    SourceRead,
    SpecInvalid,
    Stage,
    StageResult,
    answer_status,
    canonical_decimal,
    field_signal_value,
    finite_float,
    is_signal_key,
    judge_reply,
    parse_scores,
    selection_envelope,
    utf8_exceeds,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.combine.spec import (
    MAX_MEMBERS,
    MAX_WEIGHT,
    REDUCE_SELECT_RULES,
    REDUCER_RULES,
    CombineContext,
    CombineSpec,
    EntropySource,
    GateSpec,
    LogprobSource,
    SignalWeights,
    StepSpec,
    declares_reply_sources,
    parse_context,
    parse_spec,
)

COMBINE_ROUTE = "/ensemble/combine/v1"
MAX_SPEC_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 64 * 1024 * 1024
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
class _Exclusion:
    """The one rule of a step that can leave a member out (E4b part 2, erd §6 X1-X2).

    ``reason`` "no_weight": the step counts a signal weight, and the member has no usable one.
    ``reason`` "no_signal": the reduce args read ``key``, and the member has no number for it.
    """

    reason: ExcludeReason
    key: str  # the signal key the rule reads


@dataclass(frozen=True, slots=True)
class _Declared:
    """One declared name, the source reader that computes it, and the source's checked args."""

    name: str
    read: SourceRead
    args: OpArgs


@dataclass(frozen=True, slots=True)
class _ReplyDeclared:
    """One declared name that the member's reply log-probabilities give (logprob, entropy).

    WHY not a ``_Declared``: its value comes from the member reader (the recorded reply), not from
    the member text, so it has no ``SourceRead``.
    """

    name: str
    source: LogprobSource | EntropySource


# The member numbers of the one member reader call: member -> reader key -> number (None: unknown).
type _ReaderNumbers = Mapping[str, Mapping[str, float | None]]


@dataclass(frozen=True, slots=True)
class _Plan:
    """The four resolved stages of one call; ``extract`` and ``normalize`` may be absent.

    ``ranks`` and ``cut``: the hooks of a select step that ranks (``top_k@1``); the cut is read
    once from the checked args.
    """

    extract: _Step[Extractor] | None
    normalize: _Step[Normalizer] | None
    reduce: _Step[ReduceOp]
    select: _Step[SelectOp]
    signal: SignalRead | None = None
    envelope: bool = False
    excludes: _Exclusion | None = None
    ranks: Callable[[Reduction, CombineInput, OpArgs], Mapping[str, int]] | None = None
    cut: Cut | None = None
    declared: tuple[_Declared | _ReplyDeclared, ...] = ()

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
        sources_expected=(plan.signal is not None and plan.signal.key in ACCOUNTING_SIGNALS)
        or declares_reply_sources(spec),
    )
    check_fallback_signals(spec.gate, context.signals)
    recorded = _signal_values(plan, spec, context, accounting)
    combine_input = _read_members(spec, plan, context, recorded)
    trace.voters = str(len(combine_input.voters))
    if not combine_input.voters:
        return _abstain(
            spec, plan, combine_input, None, "no_votes", recorded=recorded, gate=_not_run(spec)
        )
    return _decide(spec, plan, combine_input, context, trace, recorded=recorded)


def _signal_values(
    plan: _Plan,
    spec: CombineSpec,
    context: CombineContext,
    accounting: AccountingReader | None,
) -> dict[str, dict[str, float | None]]:
    """Each member's recorded signals: the key the spec reads, then every declared name (EV-I2)."""
    keys = _recorded_keys(plan)
    if not keys:
        return {member: {} for member in spec.members}
    if not any(member in context.outputs for member in spec.members):
        # WHY no read (OME-1557): an empty quorum panel abstains with no_votes; reading a signal
        # over no member (a judge reply above all) could only refuse a Case that has no answer.
        return {member: {key: None for key in keys} for member in spec.members}
    by_name = {item.name: item for item in plan.declared}
    looked = _reader_numbers(keys, by_name, context, accounting)
    columns = {key: _column(key, by_name.get(key), spec, context, looked) for key in keys}
    return {member: {key: columns[key][member] for key in keys} for member in spec.members}


def _reader_numbers(
    keys: tuple[str, ...],
    by_name: Mapping[str, _Declared | _ReplyDeclared],
    context: CombineContext,
    accounting: AccountingReader | None,
) -> _ReaderNumbers:
    """The ONE member reader call of a combine call (C5), made only when a recorded key needs it:
    an accounting signal, or a logprob or entropy name. Empty when no key needs it.

    WHY once: the reader logs a count-only warning per call; two calls would log it twice.
    """
    if not any(
        key in ACCOUNTING_SIGNALS or isinstance(by_name.get(key), _ReplyDeclared) for key in keys
    ):
        return {}
    # WHY the reader is a port: the core does no I/O and has no recorder; the adapter knows
    # what each source call cost and what each reply carried.
    if context.sources is None:  # parse_context required them for these keys
        raise RuntimeError(
            "combine context sources are missing for an accounting or reply-logprob signal"
        )
    # WHY only the members that answered (OME-1557): a member a quorum panel left out has no
    # recorded call to match, so asking for it would only log a false warning.
    asked = MappingProxyType({m: c for m, c in context.sources.items() if m in context.outputs})
    return {} if accounting is None else accounting(asked)


def _column(
    key: str,
    item: _Declared | _ReplyDeclared | None,
    spec: CombineSpec,
    context: CombineContext,
    looked: _ReaderNumbers,
) -> Mapping[str, float | None]:
    """One recorded key's number for each member, from its source."""
    if isinstance(item, _Declared):
        return _declared_numbers(item, spec, context)
    if isinstance(item, _ReplyDeclared):
        return _reply_numbers(item.source, spec, context, looked)
    return _signal_numbers(key, spec, context, looked)


def _recorded_keys(plan: _Plan) -> tuple[str, ...]:
    read = () if plan.signal is None else (plan.signal.key,)
    return (*read, *(item.name for item in plan.declared if item.name not in read))


def _signal_numbers(
    key: str,
    spec: CombineSpec,
    context: CombineContext,
    looked: _ReaderNumbers,
) -> Mapping[str, float | None]:
    """One number (or None) for each member, from the source that the signal key names."""
    if key in ACCOUNTING_SIGNALS:
        # Without a reader (``looked`` is empty) every member's number is unknown.
        return {m: finite_float(looked.get(m, {}).get(key)) for m in spec.members}
    if key == JUDGE_SIGNAL:
        # WHY strict (F4): the judge reply format is the contract; judge reducers fail the same way.
        present = [member for member in spec.members if member in context.outputs]
        scores = parse_scores(judge_reply(context.signals, JUDGE_SIGNAL), present)
        return {member: scores.get(member) for member in spec.members}
    return _field_numbers(key[len(FIELD_SIGNAL_PREFIX) :], spec, context)


def _reply_numbers(
    source: LogprobSource | EntropySource,
    spec: CombineSpec,
    context: CombineContext,
    looked: _ReaderNumbers,
) -> dict[str, float | None]:
    """One logprob or entropy value per member, from the member's reply numbers (C5). None for a
    member that a quorum panel left out, or whose reply numbers are unknown.

    An entropy is None too when the member call did not ask for the declared ``top_logprobs``: an
    entropy over another k is not the declared signal (C1, C2). One count-only warning per step.
    """
    numbers: dict[str, float | None] = {}
    other_k = 0
    declared_k = str(source.top_logprobs) if isinstance(source, EntropySource) else None
    for member in spec.members:
        row = looked.get(member) if member in context.outputs else None
        if row is None:
            numbers[member] = None
        elif isinstance(source, LogprobSource):
            tokens = finite_float(row.get(REPLY_TOKENS))
            total = finite_float(row.get(REPLY_LOGPROB_SUM))
            numbers[member] = logprob_value(tokens, total, source.form)
        else:
            value = entropy_value(finite_float(row.get(REPLY_ENTROPY_MEAN)))
            if value is not None and _asked_top_logprobs(member, context) != declared_k:
                other_k += 1
                value = None
            numbers[member] = value
    if other_k:
        logger.warning(
            "combine entropy: %d member(s) asked for a top_logprobs other than the declared one",
            other_k,
        )
    return numbers


def _asked_top_logprobs(member: str, context: CombineContext) -> str | None:
    """The ``top_logprobs`` param text of the member's one source call; None without one such
    call, or when that call has no such param.

    WHY the source fingerprint and not ``ReplyLogprobs.top_k``: the reader matches this exact
    fingerprint to the recorded call, and the connector sets ``top_k`` from the same body param,
    so both give the same k; the fingerprint is already in the core and keeps the port keys as
    they are.
    WHY a text compare: the caller compares this text with ``str(k)``, so another spelling of the
    same k (``" 5"``) reads as another k and gives None, the safe side. The SDK always writes the
    canonical text.
    """
    # parse_context requires the sources when the spec declares a reply source.
    calls = cast("MemberSources", context.sources)[member]
    if len(calls) != 1:
        return None
    ((_, params),) = calls.values()
    return dict(params).get("top_logprobs")


def _declared_numbers(
    declared: _Declared, spec: CombineSpec, context: CombineContext
) -> dict[str, float | None]:
    numbers: dict[str, float | None] = {}
    for member in spec.members:
        text = context.outputs.get(member)  # None: a quorum panel left the member out
        if text is None or utf8_exceeds(text, MAX_OUTPUT_READ_BYTES):
            numbers[member] = None
        else:
            numbers[member] = finite_float(declared.read(text, declared.args))
    return numbers


def _field_numbers(
    path: str, spec: CombineSpec, context: CombineContext
) -> dict[str, float | None]:
    numbers: dict[str, float | None] = {}
    for member in spec.members:
        text = context.outputs.get(member)  # None: a quorum panel left the member out
        if text is None or utf8_exceeds(text, MAX_OUTPUT_READ_BYTES):
            numbers[member] = None
        else:
            numbers[member] = field_signal_value(text, path)
    return numbers


def _decide(
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    context: CombineContext,
    trace: _Trace,
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
) -> CombineOutcome:
    """Run reduce, then select, then the gate when the spec has one (E4b part 5).

    Three things may abstain: the reduce and the select steps (by raising ``NoVotes``) and the gate
    (``gate_not_met``). When reduce or select abstains, the gate does not run (GR-I1, P10).
    """
    try:
        reduction = plan.reduce.run(combine_input, plan.reduce.args)
        _check_tally(reduction, combine_input.members, plan.reduce.op_id)
    except NoVotes as exc:
        return _abstain(
            spec, plan, combine_input, None, exc.reason, recorded=recorded, gate=_not_run(spec)
        )
    try:
        selection = plan.select.run(reduction, combine_input, plan.select.args)
    except NoVotes as exc:
        return _abstain(
            spec, plan, combine_input, reduction, exc.reason, recorded=recorded, gate=_not_run(spec)
        )
    return _choose(
        spec, plan, combine_input, context, reduction, selection, trace, recorded=recorded
    )


def _choose(
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    context: CombineContext,
    reduction: Reduction,
    selection: Selection,
    trace: _Trace,
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
) -> CombineOutcome:
    """The selection's own answer (today's path), or the branch the gate takes."""
    if spec.gate is not None:
        return _gated(
            spec.gate,
            spec,
            plan,
            combine_input,
            context,
            reduction,
            selection,
            trace,
            recorded=recorded,
        )
    output = _output(selection, plan.select.op_id, context)
    trace.agreement = "-" if selection.agreement is None else str(selection.agreement)
    trace.tie = "true" if selection.tie else "false"
    result = _result(selection, REDUCER_RULES[spec.reducer].kind, output, combine_input)
    return CombineOutcome(
        output,
        _evidence(spec, plan, combine_input, reduction, selection, result, recorded=recorded),
    )


def _gated(
    gate: GateSpec,
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    context: CombineContext,
    reduction: Reduction,
    selection: Selection,
    trace: _Trace,
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
) -> CombineOutcome:
    """Compare the gate number with the threshold, record it, and take one branch (ans:Q1).

    True: the majority answer. False: the fallback (abstain, judge or writer). FB-I1: the majority
    branch never reads a fallback reply, so E4c can skip that call with no wire change.
    """
    observed = observed_number(gate, selection, recorded, combine_input.members)
    passed = passes(observed, gate.cmp, gate.threshold)
    record = GateRecord(
        observe=gate.observe,
        observed=observed,
        cmp=gate.cmp,
        threshold=float(gate.threshold),
        passed=passed,
        branch="majority" if passed else "fallback",
        otherwise=gate.otherwise,
    )
    trace.agreement = "-" if selection.agreement is None else str(selection.agreement)
    trace.tie = "true" if selection.tie else "false"
    if passed:
        output = _output(selection, plan.select.op_id, context)
        result = _result(selection, REDUCER_RULES[spec.reducer].kind, output, combine_input)
        evidence = _evidence(
            spec, plan, combine_input, reduction, selection, result, recorded=recorded, gate=record
        )
        return CombineOutcome(output, evidence)
    if gate.otherwise == "abstain":
        return _abstain(
            spec,
            plan,
            combine_input,
            reduction,
            "gate_not_met",
            recorded=recorded,
            selection=selection,
            gate=record,
        )
    return _fallback(
        gate, record, spec, plan, combine_input, context, reduction, selection, recorded=recorded
    )


def _fallback(
    gate: GateSpec,
    record: GateRecord,
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    context: CombineContext,
    reduction: Reduction,
    selection: Selection,
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
) -> CombineOutcome:
    """The judge or the writer fallback answer (gate-decision §2 delta 4, P14).

    Judge: the label member's text, byte for byte; the reading goes into the evidence ``judge``.
    Writer: the reply text is the output (8 MiB cap first); the value is the vote's own extract and
    normalize of that text (``_stages``), None when nothing is extracted.
    The vote's tally, agreement and tie stay in the evidence.
    """
    if gate.otherwise == "judge":
        reading = fallback_label(context.signals, _kept(combine_input, plan.excludes))
        final = Selection(
            chosen=(cast("str", reading.parsed),),
            tie=selection.tie,
            agreement=selection.agreement,
        )
        output = _output(final, plan.select.op_id, context)
        result = _result(final, REDUCER_RULES[spec.reducer].kind, output, combine_input)
        reduction = replace(reduction, judge=reading)
    else:
        text = fallback_text(context.signals)
        final = Selection(chosen=(), output=text, tie=selection.tie, agreement=selection.agreement)
        output = _output(final, plan.select.op_id, context)  # InputTooLarge over 8 MiB, first
        result = ResultRecord(
            member_id=None, value=_stages(text, plan)[2], status="answered", reason=None
        )
    evidence = _evidence(
        spec, plan, combine_input, reduction, final, result, recorded=recorded, gate=record
    )
    return CombineOutcome(output, evidence)


def _kept(combine_input: CombineInput, excludes: _Exclusion | None) -> tuple[str, ...]:
    """GD-E6: the present members that the step did not exclude, in spec order.

    The same rule writes the member records (``_record_status``), so a fallback label can never name
    a member that the evidence marks ``excluded`` (CE-I3).
    """
    answers = {answer.member_id: answer for answer in combine_input.answers}
    return tuple(
        member
        for member in combine_input.present
        if _record_status(answers[member], excludes)[0] != "excluded"
    )


def _not_run(spec: CombineSpec) -> GateRecord | None:
    """GR-I1, P10: the record of a gate that did not run (the vote found no answer); None when the
    spec has no gate. The fallback reply is not read."""
    gate = spec.gate
    if gate is None:
        return None
    return GateRecord(
        observe=gate.observe,
        observed=None,
        cmp=gate.cmp,
        threshold=float(gate.threshold),
        passed=None,
        branch=None,
        otherwise=gate.otherwise,
    )


def _abstain(
    spec: CombineSpec,
    plan: _Plan,
    combine_input: CombineInput,
    reduction: Reduction | None,
    reason: AbstainReason,
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
    selection: Selection | None = None,
    gate: GateRecord | None = None,
) -> CombineOutcome:
    """The normal output of a step that finds no answer: an abstain result, and the text the next
    stage gets.

    That text is empty, except for a select step that hands on the selection envelope (Rank and
    Filter): it hands on the empty envelope ``{"input":"...","selected":[]}``, so the next stage
    still sees the input (E4b ans:Q7 with ans:Q4). The 8 MiB result cap applies to it too.
    A gate abstain (gate_not_met) passes the vote's selection, so the evidence keeps the tally, the
    agreement and the tie (P14).
    """
    output = selection_envelope((), combine_input) if plan.envelope else ""
    if utf8_exceeds(output, MAX_RESULT_BYTES):
        raise InputTooLarge("the combine output exceeds 8 MiB")
    result = ResultRecord(member_id=None, value=None, status="abstain", reason=reason)
    evidence = _evidence(
        spec, plan, combine_input, reduction, selection, result, recorded=recorded, gate=gate
    )
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


def _cut(select: OperatorDescriptor | None, bound: _Step[SelectOp] | None) -> Cut | None:
    """The cut that the select step declares (``top_k@1``), from its bound args; else None.

    WHY the bound step: ``_bind`` made it after it checked the args, and the hook reads ``k``
    without a check.
    """
    if select is None or select.cut is None or bound is None:
        return None
    return select.cut(bound.args)


def _plan(spec: CombineSpec, registry: OperatorRegistry) -> _Plan:
    # WHY resolve ALL four steps before checking any args: an unknown operator is the more basic
    # failure, so it wins over bad args of an earlier step. Stage order: extract, normalize,
    # reduce, select.
    extract = _resolve(registry, spec.extract, "extract")
    normalize = _resolve(registry, spec.normalize, "normalize")
    reduce = registry.resolve(spec.reduce.op, "reduce")
    select = _resolve(registry, spec.select, "select")
    _check_pairing(reduce.id, None if select is None else select.id)
    # WHY this order: the arg checks run reduce, extract, normalize, select (a bad reduce arg wins).
    bound_reduce = cast("_Step[ReduceOp]", _bind(reduce, spec.reduce))
    bound_extract = cast("_Step[Extractor] | None", _bind(extract, spec.extract))
    bound_normalize = cast("_Step[Normalizer] | None", _bind(normalize, spec.normalize))
    bound_select = cast("_Step[SelectOp]", _bind(select, spec.select))
    declared = _declared(spec, registry)
    from_weights, from_reduce = _signal_sources(spec, reduce, bound_reduce)
    return _Plan(
        extract=bound_extract,
        normalize=bound_normalize,
        reduce=bound_reduce,
        select=bound_select,
        signal=from_reduce if from_weights is None else from_weights,
        envelope=select is not None and select.envelope,
        excludes=_exclusion(reduce, from_weights, from_reduce),
        ranks=None if select is None else select.ranks,
        cut=_cut(select, bound_select),
        declared=declared,
    )


def _check_pairing(reduce_id: str, select_id: str | None) -> None:
    """A reduce op named in ``REDUCE_SELECT_RULES`` pairs only with the select ops it lists.

    It reads the ids of the resolved descriptors. The message names the rule from the table,
    never the select id of the spec.
    """
    selects = REDUCE_SELECT_RULES.get(reduce_id)
    if selects is not None and select_id not in selects:
        raise SpecInvalid(f"{reduce_id} pairs only with select {', '.join(sorted(selects))}")


def _declared(
    spec: CombineSpec, registry: OperatorRegistry
) -> tuple[_Declared | _ReplyDeclared, ...]:
    if spec.signals is None:
        return ()
    found: list[_Declared | _ReplyDeclared] = []
    for name, source in spec.signals.items():
        if isinstance(source, LogprobSource | EntropySource):
            found.append(_ReplyDeclared(name, source))  # read from the reply, not the text
            continue
        descriptor = registry.source(source.source)
        args: OpArgs = MappingProxyType(source.model_dump(exclude={"source"}, exclude_unset=True))
        try:
            descriptor.check_args(args)
        except SpecInvalid as exc:
            raise SpecInvalid(
                f"declared signal source {descriptor.name} is invalid: {exc}"
            ) from exc
        found.append(_Declared(name, descriptor.read, args))
    return tuple(found)


def _signal_sources(
    spec: CombineSpec, reduce: OperatorDescriptor, bound: _Step[ReduceOp]
) -> tuple[SignalRead | None, SignalRead | None]:
    """The two sources of the one signal the spec reads: ``weights``, and the reduce args (F6).

    Each source is read and checked once, here; at most one of the two is set. The plan's signal
    is the one that is set, and ``_exclusion`` reads both.
    """
    from_weights = (
        SignalRead(spec.weights.signal) if isinstance(spec.weights, SignalWeights) else None
    )
    hook = reduce.signal_read
    from_reduce = None if hook is None else hook(bound.args)
    if from_reduce is not None:
        if not _known(from_reduce.key, spec):
            raise SpecInvalid(f"{bound.op_id} reads an unknown signal")
        if from_reduce.order not in (None, "max", "min"):
            raise RuntimeError(f"{bound.op_id} returned an invalid signal read")  # a plugin bug
    if from_weights is not None and not _known(from_weights.key, spec):
        raise SpecInvalid("weights reads an undeclared signal")
    if from_weights is not None and from_reduce is not None:
        raise SpecInvalid("a combine step reads at most one signal")
    return from_weights, from_reduce


def _exclusion(
    reduce: OperatorDescriptor, from_weights: SignalRead | None, from_reduce: SignalRead | None
) -> _Exclusion | None:
    """Which rule of this step can leave a member out (E4b part 2, P13, erd §6).

    X1: the spec weights are a signal and the reduce op counts weights -> "no_weight".
    X2: the reduce args read a signal (``signal_read``) -> "no_signal".
    X4, X5, X6: no rule, so no member is excluded.
    WHY the two sources, not the plan's one signal: that merges them, and the reason depends on
    which source it was. ``_signal_sources`` read and checked both; at most one is set.
    INVARIANT: the rule is read from the spec, not reported by the operator, so it holds only
    because no select op can choose a member the rule leaves out (CE-I3). ``REDUCE_SELECT_RULES``
    enforces it: a reduce op with such a rule pairs only with the selects that honor it
    (``_check_pairing``), and test_combine_exclusion_never_chosen runs every accepted pairing.
    """
    if from_weights is not None and reduce.reads_weights:
        return _Exclusion("no_weight", from_weights.key)
    return None if from_reduce is None else _Exclusion("no_signal", from_reduce.key)


def _known(key: str, spec: CombineSpec) -> bool:
    """An E4a key, or a name this spec declares (contracts C1: the plan-level key check)."""
    return is_signal_key(key) or (spec.signals is not None and key in spec.signals)


def _read_members(
    spec: CombineSpec,
    plan: _Plan,
    context: CombineContext,
    recorded: Mapping[str, Mapping[str, float | None]],
) -> CombineInput:
    """One ``Answer`` per member in spec order. An Answer's signals hold only the key the spec
    reads (I-S3 for operators); the evidence records every declared name too (EV-I2)."""
    read = () if plan.signal is None else (plan.signal.key,)
    answers = tuple(
        _answer(
            member,
            context.outputs.get(member),
            plan,
            MappingProxyType({key: recorded[member][key] for key in read}),
            _weight(spec, member, recorded[member]),
        )
        for member in spec.members
    )
    return CombineInput(
        answers=answers, outputs=context.outputs, signals=context.signals, input=context.input
    )


def _weight(spec: CombineSpec, member: str, signals: Mapping[str, float | None]) -> Decimal | None:
    """The member's vote weight from its one source: as authored, or a usable signal number."""
    weights = spec.weights
    if isinstance(weights, SignalWeights):
        number = signals[weights.signal]
        return Decimal(str(number)) if number is not None and 0 < number <= MAX_WEIGHT else None
    return None if weights is None else Decimal(str(weights[member]))


def _answer(
    member_id: str,
    text: str | None,
    plan: _Plan,
    signals: Mapping[str, float | None],
    weight: Decimal | None,
) -> Answer:
    if text is None:
        # A quorum panel left the member out (OME-1557): it is a failed member, never a vote.
        return Answer(member_id, None, None, "fail", "missing", signals, weight)
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
    *,
    recorded: Mapping[str, Mapping[str, float | None]],
    gate: GateRecord | None = None,
) -> CombineEvidence:
    # An abstain has no selection (a gate abstain has one: P14), and none or only part of a
    # reduction (a select step may abstain).
    reduction = Reduction() if reduction is None else reduction
    scores = reduction.scores or {}
    # E4b part 2 (P6, P7): the rank of each scored member of a top_k@1 step, also on an abstain.
    ranks = {} if plan.ranks is None else plan.ranks(reduction, combine_input, plan.select.args)
    statistic = reduction.statistic
    is_mean = spec.reducer == "mean"
    return CombineEvidence(
        kind=REDUCER_RULES[spec.reducer].kind,
        reducer=spec.reducer,
        operators=list(plan.operators),
        members=[
            _member_record(
                answer,
                scores,
                recorded[answer.member_id],
                plan.excludes,
                rank=ranks.get(answer.member_id),
            )
            for answer in combine_input.answers
        ],
        tally=_tally_records(reduction),
        judge=_judge_record(reduction),
        fields=_field_records(reduction, plan.reduce.op_id),
        chosen=[] if result.status == "abstain" or selection is None else list(selection.chosen),
        built=result.status == "answered"
        and selection is not None
        and selection.output is not None,
        agreement=(
            None
            if selection is None or selection.agreement is None
            else _finite(selection.agreement)
        ),
        tie=selection is not None and selection.tie,
        median=None if statistic is None or is_mean else canonical_decimal(statistic),
        mean=canonical_decimal(statistic) if is_mean and statistic is not None else None,
        presentation_order=_presentation_order(combine_input, gate),
        separator_collision=reduction.separator_collision,
        signal=None
        if plan.signal is None
        else SignalRecord(key=plan.signal.key, order=plan.signal.order),
        cut=None if plan.cut is None else CutRecord(k=plan.cut.k, order=plan.cut.order),
        declared=_declared_record(spec),
        gate=gate,
        result=result,
        dropped=sum(answer.status == "fail" for answer in combine_input.answers),
        finish_reason="stop",
    )


def _presentation_order(
    combine_input: CombineInput, gate: GateRecord | None
) -> Literal["author"] | None:
    """ "author" when the step read a judge: the context ``judge`` signal, or a fallback judge that
    the gate branch used (E4b part 5, P14)."""
    fallback_judge = gate is not None and gate.branch == "fallback" and gate.otherwise == "judge"
    return "author" if "judge" in combine_input.signals or fallback_judge else None


def _declared_record(spec: CombineSpec) -> dict[str, dict[str, JsonValue]] | None:
    if spec.signals is None:
        return None
    return {
        name: source.model_dump(mode="json", exclude_unset=True)
        for name, source in spec.signals.items()
    }


def _member_record(
    answer: Answer,
    scores: Mapping[str, Decimal],
    recorded: Mapping[str, float | None],
    excludes: _Exclusion | None,
    *,
    rank: int | None,
) -> AnswerRecord:
    status, reason = _record_status(answer, excludes)
    return AnswerRecord(
        member_id=answer.member_id,
        raw=answer.raw,
        value=answer.value,
        status=status,
        reason=reason,
        signals=dict(recorded),
        weight=None if answer.weight is None else _finite(answer.weight),
        score=_finite(scores[answer.member_id]) if answer.member_id in scores else None,
        rank=rank,
    )


def _record_status(
    answer: Answer, excludes: _Exclusion | None
) -> tuple[RecordStatus, AnswerReason | ExcludeReason | None]:
    """The record status: the member's own, or "excluded" when the step's rule left it out.

    X3: a failure wins over an exclusion, so only an answered member can be excluded. The core
    ``Answer`` stays "answered" (I-A3, AR-I5): the operators saw the same input as before.
    """
    if excludes is None or answer.status != "answered":
        return answer.status, answer.reason
    left_out = (
        answer.weight is None
        if excludes.reason == "no_weight"
        else answer.signals.get(excludes.key) is None
    )
    return ("excluded", excludes.reason) if left_out else ("answered", None)


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
