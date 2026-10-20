"""What one deterministic combine step read and decided for one Case (OME-1289).

INVARIANT: evidence never holds the ``output`` copies. The text of each member is on that member's
own operation ``output``; the evidence holds the readings, the tally or scores, and the choice. A
reading's ``raw``/``value`` is the extracted value, so an extractor such as ``whole@1`` or
``json_object@1`` puts the whole reply there.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast, get_args

from screamingface._immutable_json import freeze_json, freeze_mapping, thaw_json, thaw_mapping
from screamingface._report_primitives import _nonblank_text, _optional_number, _required_number
from screamingface._signals import is_signal_key, is_signal_name
from screamingface.answer import (
    _MEMBER_ID,
    ABSTAIN_REASONS,
    ANSWER_REASONS,
    EXCLUDE_REASONS,
    MEMBER_STATUSES,
    SIGNAL_ORDERS,
    AbstainReason,
    AnswerReason,
    MemberStatus,
    SignalOrder,
    frozen_signals,
)
from screamingface.reducer import _MAX_REDUCER_MEMBERS, REDUCER_KINDS, REDUCER_NAMES, _ReducerKind

COMBINE_EVIDENCE_SCHEMA = "screamingface.combine-evidence.v1"

type CombineKind = _ReducerKind
type ResultStatus = Literal["answered", "abstain"]
type JudgeReturns = Literal["label", "scores"]
# E4b part 5: the words of a vote gate. ``GateCmp`` is the condition that keeps the majority.
type GateCmp = Literal[">=", ">", "<=", "<"]
# E4b part 6: "band" = inside the abstain band, no comparison.
type GateBranch = Literal["majority", "fallback", "band"]
type GateOtherwise = Literal["abstain", "judge", "writer"]

# One source for each vocabulary: the Literal is the list, the set is derived from it.
_RESULT_STATUSES = frozenset(get_args(ResultStatus.__value__))
_RETURNS = frozenset(get_args(JudgeReturns.__value__))
_GATE_CMPS = frozenset(get_args(GateCmp.__value__))
_GATE_BRANCHES = frozenset(get_args(GateBranch.__value__))
_GATE_OTHERWISE = frozenset(get_args(GateOtherwise.__value__))
_GATE_SOURCES = ("chosen", "mean")
_OPERATOR_ID = re.compile(r"[a-z][a-z0-9_]*@[1-9][0-9]*")
_MAX_CUT_K = _MAX_REDUCER_MEMBERS  # the bound of sf.Rank k (blocks.py _MAX_K)
# The Engine ports MAX_NARROW_STEPS (the narrow PRD, O10): the most narrow records of one evidence.
MAX_NARROW_STEPS = 4


@dataclass(frozen=True, slots=True)
class CombineAnswerRow:
    """What the combine step read from one member's answer (the evidence Answer row, no text).

    INVARIANT (I-E1): the member text lives on the member operation's own output, never here.
    ``status`` "excluded" (E4b part 2): the member answered and a rule of the step left it out; the
    row keeps its value. ``rank`` (a top_k@1 step only) is 1 for the first member in the cut order.
    """

    member_id: str
    raw: str | None
    value: str | None
    status: MemberStatus
    reason: AnswerReason | None
    signals: Mapping[str, float | None]
    weight: float | None = None
    score: float | None = None
    rank: int | None = None

    def __post_init__(self) -> None:
        _member_id(self.member_id, "Combine answer row member_id")
        _optional_text(self.raw, "Combine answer row raw")
        _optional_text(self.value, "Combine answer row value")
        _one_of(self.status, MEMBER_STATUSES, "Combine answer row status")
        if self.reason is not None:
            _one_of(self.reason, ANSWER_REASONS, "Combine answer row reason")
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("Combine answer row has a reason exactly when it did not answer")
        if self.status == "fail" and self.value is not None:
            raise ValueError("Combine answer row of a failed member has no value")
        if self.status == "fail" and self.reason in ABSTAIN_REASONS:
            raise ValueError(
                "Combine answer row of a failed member has a failure reason, not an abstain reason"
            )
        if (self.status == "excluded") != (self.reason in EXCLUDE_REASONS):
            raise ValueError(
                "Combine answer row has an exclude reason exactly when it was excluded"
            )
        object.__setattr__(self, "signals", frozen_signals(self.signals, "Combine answer signals"))
        object.__setattr__(
            self, "weight", _optional_number(self.weight, "Combine answer row weight")
        )
        object.__setattr__(self, "score", _optional_number(self.score, "Combine answer row score"))
        object.__setattr__(self, "rank", _rank(self.rank, self.score))

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "raw": self.raw,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "signals": dict(self.signals),
            "weight": self.weight,
            "score": self.score,
            # E4b part 2: optional on the wire
            **({} if self.rank is None else {"rank": self.rank}),
        }


@dataclass(frozen=True, slots=True)
class CombineResult:
    """The computed answer of the step: a member's text, a built text, or an abstain."""

    member_id: str | None
    value: str | None
    status: ResultStatus
    reason: AbstainReason | None

    def __post_init__(self) -> None:
        if self.member_id is not None:
            _member_id(self.member_id, "Combine result member_id")
        _optional_text(self.value, "Combine result value")
        _one_of(self.status, _RESULT_STATUSES, "Combine result status")
        if self.reason is not None:
            _one_of(self.reason, ABSTAIN_REASONS, "Combine result reason")
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("Combine result has a reason exactly when it abstained")
        if self.status == "abstain" and (self.value is not None or self.member_id is not None):
            raise ValueError("an abstain Combine result has no value and no member")

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CombineSignal:
    """The one signal the spec reads, and the order a reducer asked for (None: no order)."""

    key: str
    order: SignalOrder | None

    def __post_init__(self) -> None:
        if not is_signal_key(self.key):
            raise ValueError("Combine signal key must be an E4a signal key")
        if self.order is not None:
            _one_of(self.order, SIGNAL_ORDERS, "Combine signal order")

    @classmethod
    def _declared(cls, key: str, order: SignalOrder | None) -> CombineSignal:
        """The read of a declared name (E4b part 3). CombineEvidence checks the name is declared."""
        if not is_signal_name(key):
            raise ValueError("Combine signal key must be an E4a signal key or a declared name")
        if order is not None:
            _one_of(order, SIGNAL_ORDERS, "Combine signal order")
        signal = object.__new__(cls)
        object.__setattr__(signal, "key", key)
        object.__setattr__(signal, "order", order)
        return signal

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "order": self.order}


@dataclass(frozen=True, slots=True)
class CombineCut:
    """The cut of a top-k step (``sf.Rank``): keep the first ``k`` scored members in ``order``.

    Each member row has its ``rank``; when the step answered, the chosen members are the rows
    with ``rank <= k``.
    """

    k: int
    order: SignalOrder

    def __post_init__(self) -> None:
        if isinstance(self.k, bool) or not isinstance(self.k, int):
            raise TypeError("Combine cut k must be an integer")
        if not 1 <= self.k <= _MAX_CUT_K:
            raise ValueError(f"Combine cut k must be between 1 and {_MAX_CUT_K}")
        _one_of(self.order, SIGNAL_ORDERS, "Combine cut order")

    def to_dict(self) -> dict[str, object]:
        return {"k": self.k, "order": self.order}


@dataclass(frozen=True, slots=True, kw_only=True)
class CombineNarrow:
    """What one narrow step (``sf.Filter`` or ``sf.Rank`` before the reducer) kept.

    ``reduce`` and ``select`` are the pinned op ids of the step (``filter@1`` + ``kept@1``,
    ``by_signal@1`` or ``scores@1`` + ``top_k@1``); ``signal`` the key the step read (None for a
    pattern filter); ``kept`` the members it chose, in author order (empty: the
    step chose none, so the Case abstained there); ``scores`` the step's score of each member it
    read that had one; ``cut`` and ``ranks`` a top-k step only, with the rules of ``CombineCut``
    and the row ``rank``.
    """

    reduce: str | None = None
    select: str
    signal: str | None = None
    kept: tuple[str, ...]
    cut: CombineCut | None = None
    scores: Mapping[str, float] | None = None
    ranks: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        _operator_ids((self.select,) if self.reduce is None else (self.reduce, self.select))
        if self.signal is not None and not (
            is_signal_key(self.signal) or is_signal_name(self.signal)
        ):
            raise ValueError("Combine narrow signal must be a signal key or a declared name")
        object.__setattr__(self, "kept", _member_ids(self.kept, "Combine narrow kept"))
        _optional_instance(self.cut, CombineCut, "Combine narrow cut")
        object.__setattr__(self, "scores", _narrow_scores(self.scores))
        object.__setattr__(self, "ranks", _narrow_ranks(self))

    def to_dict(self) -> dict[str, object]:
        # Keys that are not set are absent on the wire (the Engine NarrowRecord).
        data: dict[str, object] = {} if self.reduce is None else {"reduce": self.reduce}
        data["select"] = self.select
        if self.signal is not None:
            data["signal"] = self.signal
        data["kept"] = list(self.kept)
        if self.cut is not None:
            data["cut"] = self.cut.to_dict()
        if self.scores is not None:
            data["scores"] = dict(self.scores)
        if self.ranks is not None:
            data["ranks"] = dict(self.ranks)
        return data


def _narrow_scores(value: object) -> Mapping[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("Combine narrow scores must be a mapping")
    _member_ids(tuple(value), "Combine narrow scores")
    return MappingProxyType(
        {key: _required_number(item, "Combine narrow score") for key, item in value.items()}
    )


def _narrow_ranks(record: CombineNarrow) -> Mapping[str, int] | None:
    """The part 2 rank rules, per narrow step: ranks only with a cut, 1..n over the scored
    members; a top k that kept members kept exactly the ranks within its cut."""
    value = record.ranks
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("Combine narrow ranks must be a mapping")
    if record.cut is None:
        raise ValueError("Combine narrow record has ranks only with a cut")
    ranks: dict[str, int] = {}
    for member, rank in value.items():
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise TypeError("Combine narrow ranks must be integers")
        ranks[member] = rank
    if set(ranks) != set(record.scores or {}) or sorted(ranks.values()) != list(
        range(1, len(ranks) + 1)
    ):
        raise ValueError("Combine narrow ranks are 1..n over the scored members")
    within = {member for member, rank in ranks.items() if rank <= record.cut.k}
    if record.kept and (set(record.kept) != within or len(record.kept) != record.cut.k):
        raise ValueError("Combine narrow top-k record keeps the members ranked within its cut")
    return MappingProxyType(ranks)


@dataclass(frozen=True, slots=True)
class CombineGate:
    """What the gate of a vote compared and which branch the step took (``sf.Gate``, E4b part 5).

    ``observe`` is ``"agreement"``, ``"chosen:<name>"`` or ``"mean:<name>"``. ``cmp`` is the
    condition that keeps the majority: when ``observed cmp threshold`` holds, ``passed`` is True
    and ``branch`` is ``"majority"``; else the ``otherwise`` fallback answered. ``passed`` and
    ``branch`` are None when the vote found no answer, so the gate did not run; ``observed`` is
    then None too. ``observed`` is also None when the gate ran and had no number to compare.
    E4b part 6 (ans:Q2): ``abstain_band`` is the spec band ``(lo, hi)`` or None. ``branch``
    ``"band"`` = the number was inside the closed band, so the step abstained with ``in_band``
    and made no comparison (``passed`` None).
    """

    observe: str
    observed: float | None
    cmp: GateCmp
    threshold: float
    passed: bool | None
    branch: GateBranch | None
    otherwise: GateOtherwise
    abstain_band: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        _gate_observe(self.observe)
        object.__setattr__(
            self, "observed", _optional_number(self.observed, "Combine gate observed")
        )
        _one_of(self.cmp, _GATE_CMPS, "Combine gate cmp")
        object.__setattr__(
            self, "threshold", _required_number(self.threshold, "Combine gate threshold")
        )
        _optional_flag(self.passed, "Combine gate passed")
        if self.branch is not None:
            _one_of(self.branch, _GATE_BRANCHES, "Combine gate branch")
        _one_of(self.otherwise, _GATE_OTHERWISE, "Combine gate otherwise")
        object.__setattr__(self, "abstain_band", _gate_band(self.abstain_band))
        _check_band_gate(self)
        if self.branch == "band":
            return  # GR-I1': the band branch has no comparison result (P10)
        # GR-I1
        if (self.passed is None) != (self.branch is None):
            raise ValueError("Combine gate has a branch exactly when it has a comparison result")
        if self.passed is None and self.observed is not None:
            raise ValueError("Combine gate that did not run observed no number")
        # GR-I2
        if self.passed is not None and self.passed != (self.branch == "majority"):
            raise ValueError("Combine gate that passed keeps the majority, and only it does")

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "observe": self.observe,
            "observed": self.observed,
            "cmp": self.cmp,
            "threshold": self.threshold,
            "passed": self.passed,
            "branch": self.branch,
            "otherwise": self.otherwise,
        }
        if self.abstain_band is not None:
            data["abstain_band"] = list(self.abstain_band)
        return data


@dataclass(frozen=True, slots=True)
class CombineSampleCount:
    """One member's extra samples of the declared ``sf.Consistency`` source (E4b part 7).

    ``succeeded`` samples answered and ``failed`` did not (ans:Q4: the failed count is recorded);
    ``matched`` of the succeeded samples gave the member's answer. The member's value, in its answer
    row ``signals``, is ``matched / succeeded``. ``matched`` is None when the member has no value:
    no sample answered, or the member has no answer to compare.
    """

    member_id: str
    matched: int | None
    succeeded: int
    failed: int

    def __post_init__(self) -> None:
        _member_id(self.member_id, "Combine sample count member_id")
        if self.matched is not None:
            _sample_number(self.matched, "Combine sample count matched")
        _sample_number(self.succeeded, "Combine sample count succeeded")
        _sample_number(self.failed, "Combine sample count failed")
        # CS-I4
        if self.matched is not None and (self.succeeded < 1 or self.matched > self.succeeded):
            raise ValueError(
                "Combine sample count matched is at most succeeded, "
                "and a match needs a successful sample"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "matched": self.matched,
            "succeeded": self.succeeded,
            "failed": self.failed,
        }


@dataclass(frozen=True, slots=True)
class CombineTallyRow:
    """One candidate value of a vote: its score and the members holding it."""

    value: str
    score: float
    holders: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.value, "Combine tally value")
        object.__setattr__(self, "score", _required_number(self.score, "Combine tally score"))
        holders = _member_ids(self.holders, "Combine tally holders")
        if not holders:
            raise ValueError("Combine tally holders must not be empty")
        object.__setattr__(self, "holders", holders)

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "score": self.score, "holders": list(self.holders)}


@dataclass(frozen=True, slots=True, init=False)
class CombineJudgeReading:
    """What a judge reply was parsed into: one member label, or one score per member."""

    raw: str
    returns: JudgeReturns
    parsed: object

    def __init__(self, *, raw: str, returns: JudgeReturns, parsed: object) -> None:
        _text(raw, "Combine judge raw")
        _one_of(returns, _RETURNS, "Combine judge returns")
        frozen = freeze_json(parsed, "Combine judge parsed")
        if returns == "label" and not isinstance(frozen, str):
            raise TypeError("Combine judge parsed must be a member label for returns 'label'")
        if returns == "scores" and not isinstance(frozen, Mapping):
            raise TypeError("Combine judge parsed must be an object for returns 'scores'")
        object.__setattr__(self, "raw", raw)
        object.__setattr__(self, "returns", returns)
        object.__setattr__(self, "parsed", frozen)

    def to_dict(self) -> dict[str, object]:
        return {"raw": self.raw, "returns": self.returns, "parsed": thaw_json(self.parsed)}


@dataclass(frozen=True, slots=True, init=False)
class CombineFieldReading:
    """One merged field: the value each member gave, the rule applied, and the result."""

    field: str
    rule: str
    values: Mapping[str, object]
    result: object

    def __init__(
        self, *, field: str, rule: str, values: Mapping[str, object], result: object
    ) -> None:
        object.__setattr__(self, "field", _text(field, "Combine field reading field"))
        object.__setattr__(self, "rule", _text(rule, "Combine field reading rule"))
        object.__setattr__(self, "values", freeze_mapping(values, "Combine field reading values"))
        object.__setattr__(self, "result", freeze_json(result, "Combine field reading result"))

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "rule": self.rule,
            "values": thaw_mapping(self.values),
            "result": thaw_json(self.result),
        }


@dataclass(frozen=True, slots=True, init=False)
class CombineEvidence:
    """What one combine step read and decided for one Case. Never holds the ``output`` copies."""

    kind: CombineKind
    reducer: str
    operators: tuple[str, ...]
    members: tuple[CombineAnswerRow, ...]
    tally: tuple[CombineTallyRow, ...] | None
    judge: CombineJudgeReading | None
    fields: tuple[CombineFieldReading, ...] | None
    chosen: tuple[str, ...]
    built: bool
    agreement: float | None
    tie: bool
    median: str | None
    mean: str | None
    presentation_order: Literal["author"] | None
    separator_collision: bool | None
    signal: CombineSignal | None
    cut: CombineCut | None
    narrow: tuple[CombineNarrow, ...] | None
    consistency: Mapping[str, tuple[CombineSampleCount, ...]] | None
    declared: Mapping[str, Mapping[str, object]] | None
    gate: CombineGate | None
    result: CombineResult
    dropped: int
    finish_reason: str

    def __init__(
        self,
        *,
        kind: CombineKind,
        reducer: str,
        operators: Sequence[str],
        members: Sequence[CombineAnswerRow],
        chosen: Sequence[str],
        built: bool,
        tie: bool,
        result: CombineResult,
        dropped: int,
        finish_reason: str,
        tally: Sequence[CombineTallyRow] | None = None,
        judge: CombineJudgeReading | None = None,
        fields: Sequence[CombineFieldReading] | None = None,
        agreement: float | None = None,
        median: str | None = None,
        mean: str | None = None,
        presentation_order: Literal["author"] | None = None,
        separator_collision: bool | None = None,
        signal: CombineSignal | None = None,
        cut: CombineCut | None = None,
        declared: Mapping[str, Mapping[str, object]] | None = None,
        gate: CombineGate | None = None,
        consistency: Mapping[str, Sequence[CombineSampleCount]] | None = None,
        narrow: Sequence[CombineNarrow] | None = None,
    ) -> None:
        _one_of(kind, REDUCER_KINDS, "Combine evidence kind")
        _one_of(reducer, REDUCER_NAMES, "Combine evidence reducer")
        selected_members = _typed_tuple(members, CombineAnswerRow, "Combine evidence members")
        member_ids = tuple(item.member_id for item in selected_members)
        if not member_ids or len(set(member_ids)) != len(member_ids):
            raise ValueError("Combine evidence members must be non-empty and unique")
        selected_tally = _optional_typed_tuple(tally, CombineTallyRow, "Combine evidence tally")
        selected_fields = _optional_typed_tuple(
            fields, CombineFieldReading, "Combine evidence fields"
        )
        _subset(chosen, member_ids, "Combine evidence chosen")
        _never_excluded(chosen, selected_members)
        for row in selected_tally or ():
            _subset(row.holders, member_ids, "Combine tally holders")
        selected_dropped = _dropped(dropped, selected_members)
        _ranks(selected_members)
        selected_chosen = tuple(chosen)
        selected_result = _result(result, selected_chosen, built)
        selected_declared = _declared_map(declared)
        selected_signal = _optional_instance(signal, CombineSignal, "Combine evidence signal")
        if (
            selected_signal is not None
            and not is_signal_key(selected_signal.key)
            and (selected_declared is None or selected_signal.key not in selected_declared)
        ):
            raise ValueError("Combine evidence signal must read an E4a key or a declared name")
        selected_judge = _optional_instance(judge, CombineJudgeReading, "Combine evidence judge")
        selected_agreement = _agreement(agreement)
        selected_gate = _optional_instance(gate, CombineGate, "Combine evidence gate")
        _gate_reason(selected_gate, selected_result)
        _check_gate(
            selected_gate,
            agreement=selected_agreement,
            judge=selected_judge,
            chosen=selected_chosen,
            built=built,
            result=selected_result,
        )
        values = {
            "kind": kind,
            "reducer": reducer,
            "operators": _operator_ids(operators),
            "members": selected_members,
            "tally": selected_tally,
            "judge": selected_judge,
            "fields": selected_fields,
            "chosen": selected_chosen,
            "built": _flag(built, "Combine evidence built"),
            "agreement": selected_agreement,
            "tie": _flag(tie, "Combine evidence tie"),
            "median": _optional_text(median, "Combine evidence median"),
            "mean": _optional_text(mean, "Combine evidence mean"),
            "presentation_order": _presentation_order(presentation_order),
            "separator_collision": _optional_flag(
                separator_collision, "Combine evidence separator_collision"
            ),
            "signal": selected_signal,
            "cut": _optional_instance(cut, CombineCut, "Combine evidence cut"),
            "narrow": _narrow(narrow, selected_members, gate=selected_gate, result=selected_result),
            "consistency": _consistency_map(consistency, selected_declared, selected_members),
            "declared": selected_declared,
            "gate": selected_gate,
            "result": selected_result,
            "dropped": selected_dropped,
            "finish_reason": _nonblank_text(finish_reason, "Combine evidence finish_reason"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": COMBINE_EVIDENCE_SCHEMA,
            "kind": self.kind,
            "reducer": self.reducer,
            "operators": list(self.operators),
            "members": [item.to_dict() for item in self.members],
            "tally": None if self.tally is None else [item.to_dict() for item in self.tally],
            "judge": None if self.judge is None else self.judge.to_dict(),
            "fields": None if self.fields is None else [item.to_dict() for item in self.fields],
            "chosen": list(self.chosen),
            "built": self.built,
            "agreement": self.agreement,
            "tie": self.tie,
            "median": self.median,
            # E4b P8: optional on the wire, only the mean reducer writes it
            **({} if self.mean is None else {"mean": self.mean}),
            "presentation_order": self.presentation_order,
            "separator_collision": self.separator_collision,
            "signal": None if self.signal is None else self.signal.to_dict(),
            **({} if self.cut is None else {"cut": self.cut.to_dict()}),  # E4b part 2: optional
            # E4b map-reduce surface: optional on the wire, only a block with narrow steps writes it
            **(
                {}
                if self.narrow is None
                else {"narrow": [record.to_dict() for record in self.narrow]}
            ),
            # E4b part 7 (P13): optional on the wire, only a Fusion with sf.Consistency writes it
            **(
                {}
                if self.consistency is None
                else {
                    "consistency": {
                        name: [record.to_dict() for record in records]
                        for name, records in self.consistency.items()
                    }
                }
            ),
            # E4b part 3 (P11): optional on the wire, only a Fusion that declares signals writes it
            **({} if self.declared is None else {"declared": thaw_mapping(self.declared)}),
            # E4b part 5 (P9): optional on the wire, only a gated vote writes it
            **({} if self.gate is None else {"gate": self.gate.to_dict()}),
            "result": self.result.to_dict(),
            "dropped": self.dropped,
            "finish_reason": self.finish_reason,
        }


def _narrow(
    value: object,
    members: tuple[CombineAnswerRow, ...],
    *,
    gate: CombineGate | None,
    result: CombineResult,
) -> tuple[CombineNarrow, ...] | None:
    """NR-I1..NR-I5 of the narrow PRD §4.3, the twin of the Engine ``_check_narrow``.

    NR-I6 is ``_dropped``; AR-I3′ is ``CombineAnswerRow``; the main-step score check of NR-I5
    reads the rows.
    """
    if value is None:
        # NR-I4
        if any(row.reason == "not_selected" for row in members):
            raise ValueError(
                "Combine evidence not_selected goes with a narrow record, and only with it"
            )
        return None
    records = _typed_tuple(value, CombineNarrow, "Combine evidence narrow")
    if not 1 <= len(records) <= MAX_NARROW_STEPS:
        raise ValueError(f"Combine evidence narrow holds 1 to {MAX_NARROW_STEPS} steps")
    _narrow_kept(records, members)
    _narrow_rows(records, members)
    if not records[-1].kept and (
        result.reason not in ("no_votes", "cut_not_met")
        or (gate is not None and gate.branch is not None)
        or any(row.score is not None for row in members)
    ):
        # NR-I5
        raise ValueError(
            "Combine evidence narrow abstain ends with no_votes or cut_not_met before the main "
            "step and the gate"
        )
    return records


def _narrow_kept(records: tuple[CombineNarrow, ...], members: tuple[CombineAnswerRow, ...]) -> None:
    """NR-I1: each ``kept`` in author order, a subset of the live set before its step."""
    position = {row.member_id: index for index, row in enumerate(members)}
    live: Sequence[str] = [row.member_id for row in members if row.status != "fail"]
    for index, record in enumerate(records):
        if not set(record.kept) <= set(live):
            raise ValueError(
                "Combine evidence kept of the first narrow step names only members that answered"
                if index == 0
                else "Combine evidence kept of a narrow step is a subset of the step before"
            )
        order = [position[member] for member in record.kept]
        if order != sorted(order):
            raise ValueError("Combine evidence narrow kept is in author order")
        if not set(record.scores or {}) <= set(live):
            raise ValueError("Combine evidence narrow scores name only the members live then")
        if not record.kept and index != len(records) - 1:
            raise ValueError("Combine evidence only the last narrow step may keep no member")
        live = record.kept


def _narrow_rows(records: tuple[CombineNarrow, ...], members: tuple[CombineAnswerRow, ...]) -> None:
    """NR-I2 and NR-I3: a member a narrow step left out is excluded by the first step that did."""
    final = set(records[-1].kept)
    for row in members:
        if row.member_id in final:
            if row.reason == "not_selected":
                raise ValueError("Combine evidence not_selected member is in no later narrow kept")
            continue
        if row.status == "fail":
            continue
        if row.reason not in ("not_selected", "no_signal"):
            raise ValueError(
                "Combine evidence member a narrow step left out is excluded with not_selected or "
                "no_signal"
            )
        if row.reason == "no_signal":
            step = next(record for record in records if row.member_id not in record.kept)
            if step.signal is None or row.signals.get(step.signal, 0.0) is not None:
                raise ValueError(
                    "Combine evidence narrow no_signal member has no value for its step's signal"
                )


def _is_gate_observe(value: str) -> bool:
    """The one SDK rule for a gate number: agreement, chosen:<name> or mean:<name> (sf.Gate too)."""
    source, separator, name = value.partition(":")
    return value == "agreement" or bool(
        separator and source in _GATE_SOURCES and is_signal_name(name)
    )


def _gate_observe(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Combine gate observe must be text")
    if not _is_gate_observe(value):
        raise ValueError("Combine gate observe must be agreement, chosen:<name> or mean:<name>")
    return value


def _gate_band(value: object) -> tuple[float, float] | None:
    """The band as a pair of finite floats (a list becomes a tuple); None: no band."""
    if value is None:
        return None
    if isinstance(value, str | bytes) or not isinstance(value, Sequence) or len(value) != 2:
        raise TypeError("Combine gate abstain_band must be two finite numbers")
    label = "Combine gate abstain_band"
    return (_required_number(value[0], label), _required_number(value[1], label))


def _check_band_gate(gate: CombineGate) -> None:
    """GB-I1, GB-I2 and GB-I3 (E4b part 6), the twin of the Engine ``_check_band_record``.

    WHY a helper: ``CombineGate.__post_init__`` is at the lint complexity limit (part 5 E3).
    """
    band = gate.abstain_band
    observed = gate.observed
    if band is not None and band[0] > band[1]:
        raise ValueError("Combine gate band is two numbers lo <= hi")
    inside = band is not None and observed is not None and band[0] <= observed <= band[1]
    if gate.branch == "band":
        if gate.passed is not None:
            raise ValueError("Combine gate in its band made no comparison")
        if not inside:
            raise ValueError("Combine gate band branch observed a number inside its band")
    elif gate.branch is not None and inside:
        raise ValueError("Combine gate that compared observed a number outside its band")


def _check_gate(
    gate: CombineGate | None,
    *,
    agreement: float | None,
    judge: CombineJudgeReading | None,
    chosen: tuple[str, ...],
    built: object,
    result: CombineResult,
) -> None:
    """GR-I1 (evidence part), GR-I4' and GR-I5 of erd §4 (GB-I4 and GR-I3: _gate_reason)."""
    if gate is None:
        return
    if gate.passed is None and result.status != "abstain":
        raise ValueError("Combine evidence gate that did not run goes with an abstained result")
    if gate.observe == "agreement" and gate.branch is not None and gate.observed != agreement:
        raise ValueError("Combine evidence agreement gate observes the evidence agreement")
    if gate.branch != "fallback":
        return
    if gate.otherwise == "writer" and not (
        built is True and not chosen and result.member_id is None
    ):
        raise ValueError("Combine evidence writer fallback builds the answer and chooses no member")
    if gate.otherwise == "judge" and (
        judge is None
        or judge.returns != "label"
        or result.member_id is None
        or chosen != (result.member_id,)
    ):
        raise ValueError(
            "Combine evidence judge fallback records its label reading and chooses that member"
        )


def _consistency_map(
    value: object,
    declared: Mapping[str, Mapping[str, object]] | None,
    members: tuple[CombineAnswerRow, ...],
) -> Mapping[str, tuple[CombineSampleCount, ...]] | None:
    """CS-I1, CS-I2, CS-I3 and CS-I5 of the E4b part 7 erd §6 (CS-I4: CombineSampleCount)."""
    names = [
        name for name, entry in (declared or {}).items() if entry.get("source") == "consistency"
    ]
    if value is None and not names:
        return None
    if value is not None and not isinstance(value, Mapping):
        raise TypeError("Combine evidence consistency must be a mapping")
    if value is None or declared is None or len(names) != 1 or list(value) != names:
        raise ValueError(
            "Combine evidence consistency record goes with one declared consistency source"
        )
    name = names[0]
    records = _typed_tuple(value[name], CombineSampleCount, "Combine evidence consistency")
    if tuple(record.member_id for record in records) != tuple(row.member_id for row in members):
        raise ValueError("Combine evidence consistency record names every member in order")
    n = declared[name].get("n")
    for record, row in zip(records, members, strict=True):
        if type(n) is not int or record.succeeded + record.failed != n:
            raise ValueError("Combine evidence succeeded and failed samples add up to n")
        expected = None if record.matched is None else record.matched / record.succeeded
        if name not in row.signals or row.signals[name] != expected:
            raise ValueError("Combine evidence consistency value is matched over succeeded")
    return MappingProxyType({name: records})


def _sample_number(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if value < 0:
        raise ValueError(f"{label} must not be negative")
    return value


def _declared_map(value: object) -> Mapping[str, Mapping[str, object]] | None:
    if value is None:
        return None
    frozen = freeze_mapping(value, "Combine evidence declared")
    if not frozen:
        raise ValueError("Combine evidence declared must name at least one signal")
    for name, entry in frozen.items():
        if not is_signal_name(name):
            raise ValueError("Combine evidence declared names must be declared signal names")
        if not isinstance(entry, Mapping) or not isinstance(entry.get("source"), str):
            raise ValueError("Combine evidence declared entries must name their source")
    return cast("Mapping[str, Mapping[str, object]]", frozen)


def _text(value: object, label: str) -> str:
    """Plain text as the Engine model carries it: any ``str``, blank included.

    WHY blank is allowed: a judge may reply with nothing, and one blank reading must not
    make the whole Report undecodable.
    """

    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _one_of(value: object, allowed: frozenset[str], label: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {', '.join(sorted(allowed))}")


def _member_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _MEMBER_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must look like 'member_1'")
    return value


def _member_ids(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be an ordered sequence of member ids")
    selected = tuple(_member_id(value, label) for value in values)
    if len(set(selected)) != len(selected):
        raise ValueError(f"{label} must be unique")
    return selected


def _subset(values: Sequence[str], members: tuple[str, ...], label: str) -> None:
    selected = _member_ids(values, label)
    if unknown := [value for value in selected if value not in members]:
        raise ValueError(f"{label} names {unknown[0]!r}, which is not a member")


def _never_excluded(chosen: Sequence[str], members: tuple[CombineAnswerRow, ...]) -> None:
    """CE-I3 (E4b part 2): a member that a rule left out is never chosen."""
    excluded = {row.member_id for row in members if row.status == "excluded"}
    if hit := [member for member in chosen if member in excluded]:
        raise ValueError(f"Combine evidence chosen names {hit[0]!r}, which is excluded")


def _operator_ids(values: object) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError("Combine evidence operators must be an ordered sequence of ids")
    for value in values:
        if not isinstance(value, str) or _OPERATOR_ID.fullmatch(value) is None:
            raise ValueError("Combine evidence operators must be pinned ids like 'mode@1'")
    return tuple(values)


def _dropped(value: object, members: tuple[CombineAnswerRow, ...]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Combine evidence dropped must be an integer")
    if value < 0 or value != sum(row.status == "fail" for row in members):
        raise ValueError("Combine evidence dropped must count the failed members")
    return value


def _rank(value: object, score: float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Combine answer row rank must be an integer")
    if value < 1:
        raise ValueError("Combine answer row rank must be at least 1")
    if score is None:
        raise ValueError("Combine answer row rank needs a score")
    return value


def _ranks(members: tuple[CombineAnswerRow, ...]) -> None:
    """AR-I4: when one row has a rank, the ranks are 1..n over the rows with a score."""
    ranks = sorted(row.rank for row in members if row.rank is not None)
    scored = sum(row.score is not None for row in members)
    if ranks and ranks != list(range(1, scored + 1)):
        raise ValueError("Combine evidence ranks must be 1..n over the members with a score")


def _result(value: object, chosen: tuple[str, ...], built: object) -> CombineResult:
    if not isinstance(value, CombineResult):
        raise TypeError("Combine evidence result must be a CombineResult")
    if value.status == "abstain" and (chosen or built):
        raise ValueError("an abstained Combine evidence chooses and builds nothing")
    if value.member_id is not None and (built or chosen != (value.member_id,)):
        raise ValueError("a member Combine result must be the one chosen member and not built")
    return value


def _gate_reason(gate: CombineGate | None, result: CombineResult) -> None:
    """GB-I4, then GR-I3: ``in_band`` goes with the band branch only (E4b part 6), and
    ``gate_not_met`` goes with a gate that took the abstain fallback only (part 5).

    WHY GB-I4 first: ``CombineEvidence.__init__`` calls this before ``_check_gate``; a band gate
    with the reason ``gate_not_met`` must fail with the ``in_band`` message (AB-E3), as in the
    Engine.
    """
    banded = gate is not None and gate.branch == "band"
    if (result.reason == "in_band") != banded:
        raise ValueError(
            "in_band goes with a gate that abstained inside its band, and only with it"
        )
    abstained = gate is not None and gate.branch == "fallback" and gate.otherwise == "abstain"
    if (result.reason == "gate_not_met") != abstained:
        raise ValueError(
            "gate_not_met goes with a gate that took the abstain fallback, and only with it"
        )


def _agreement(value: object) -> float | None:
    selected = _optional_number(value, "Combine evidence agreement")
    if selected is not None and not 0.0 <= selected <= 1.0:
        raise ValueError("Combine evidence agreement must be between 0 and 1")
    return selected


def _flag(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a bool")
    return value


def _optional_flag(value: object, label: str) -> bool | None:
    return None if value is None else _flag(value, label)


def _presentation_order(value: object) -> Literal["author"] | None:
    if value is None:
        return None
    if value != "author":
        raise ValueError("Combine evidence presentation_order must be 'author' or None")
    return "author"


def _typed_tuple[T](values: object, kind: type[T], label: str) -> tuple[T, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be an ordered sequence")
    selected = tuple(values)
    if any(not isinstance(item, kind) for item in selected):
        raise TypeError(f"{label} must contain only {kind.__name__} values")
    return selected


def _optional_typed_tuple[T](values: object, kind: type[T], label: str) -> tuple[T, ...] | None:
    return None if values is None else _typed_tuple(values, kind, label)


def _optional_instance[T](value: object, kind: type[T], label: str) -> T | None:
    if value is not None and not isinstance(value, kind):
        raise TypeError(f"{label} must be a {kind.__name__} or None")
    return value


__all__ = [
    "COMBINE_EVIDENCE_SCHEMA",
    "CombineAnswerRow",
    "CombineCut",
    "CombineEvidence",
    "CombineFieldReading",
    "CombineGate",
    "CombineJudgeReading",
    "CombineNarrow",
    "CombineResult",
    "CombineSampleCount",
    "CombineSignal",
    "CombineTallyRow",
]
