"""The strict parsers of a combine call's two payloads (OME-1289 E4a).

FEATURE: read the spec (``screamingface.combine-spec.v1``, the url4 ``intent``) and the context
(the member outputs and signals) of one combine call, and reject anything off-contract.
STORY: as the endpoint, I get a typed spec and context or a ``SpecInvalid`` -- never a half-read
payload, and never an error message that repeats what a member or a judge wrote.

INVARIANT: every key of the spec is always present except the optional ``signals`` (E4b part 3)
and ``gate`` (E4b part 5); ``null`` is allowed only where the type says so. Unknown keys,
duplicate JSON keys, NaN/Infinity and nesting beyond 64 levels are rejected. The ``gate`` object
has one optional key of its own, ``abstain_band`` (E4b part 6).
INVARIANT: a failure message names locations and rules, never input values.
The spec text is the SDK's canonical JSON with ``$`` written as ``\\u0024``; ``json.loads`` gives
the ``$`` back, so this parser needs no url4 escape handling.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

from screamingface_engine.combine.ports import (
    GATE_OBSERVE,
    MAX_DECLARED_SIGNALS,
    CallFingerprint,
    EvidenceKind,
    GateCmp,
    GateOtherwise,
    MemberSources,
    Reducer,
    SpecInvalid,
    is_signal_key,
    is_signal_name,
    loads_bounded,
)

COMBINE_SPEC_SCHEMA = "screamingface.combine-spec.v1"
_OP_ID = r"^[a-z][a-z0-9_]{0,47}@[1-9][0-9]{0,5}$"
_MEMBER = re.compile(r"member_[1-9][0-9]*")
# E4b part 5 (P18): the context signal keys of the gate fallback replies.
FALLBACK_JUDGE = "fallback_judge"
FALLBACK_WRITER = "fallback_writer"
# WHY `_SIGNAL` spells the two fallback keys again: the SDK conformance tests read `_SIGNAL` from
# this file's syntax tree as one string literal, so the pattern cannot be built from the names.
# WHY "writer_" and not "writer.": the SDK builds the context with url4 struct, whose keys are
# [A-Za-z0-9_]+ only, so a dotted signal key cannot be written (OME-1289 unit 8-10 spec, P1).
_SIGNAL = re.compile(r"judge|fallback_judge|fallback_writer|writer_[A-Za-z_][A-Za-z0-9_]*")
_CONTEXT_KEYS = frozenset({"input", "outputs", "panel", "samples", "signals", "sources"})
_PANEL_ROW_KEYS = frozenset({"source_position", "source_name", "result"})
_CALL_KEY = re.compile(r"[A-Za-z0-9_]+")
_MAX_ERRORS_SHOWN = 5
_MAX_LOCATION_CHARS = 64
MAX_MEMBERS = 256
# WHY this cap: a reducer may sum weights, and a sum over every member must stay a finite float
# (an `inf` score cannot be recorded as evidence). `MAX_MEMBERS` such weights sum to at most the
# largest float.
MAX_WEIGHT = sys.float_info.max / MAX_MEMBERS
_MEDIAN_NORMALIZER = "numeric"

Presence = Literal["required", "optional", "forbidden"]


@dataclass(frozen=True, slots=True)
class ReducerRule:
    """What a reducer needs, allows or forbids, and the evidence kind it makes.

    ``normalize_name`` is the one operator NAME (any version) its normalize step must have, or
    None for any. It is the only operator rule in this row. E4b adds three operator rules outside
    the rows, as a deliberate exception (erratum ER7): `_STATISTIC_REDUCERS` and `_MEAN_OPS`
    (part 1; they match operator NAMES, any version, when the spec is parsed) and
    ``REDUCE_SELECT_RULES`` (part 2, ER1, ER2; it pairs a reduce op with its select ops and
    matches exact operator ids, in the endpoint `_plan`).
    """

    kind: EvidenceKind
    extract: Presence
    normalize: Presence
    weights: Presence
    normalize_name: str | None = None


# Global rule (also checked below): normalize present => extract present.
# AIDEV-NOTE: units 8-10 may tighten or loosen the presence rows of their own reducers, and still
# add no operator rule. E4b adds three operator rules below on purpose (erratum ER7): the median
# and mean rules `_STATISTIC_REDUCERS` and `_MEAN_OPS` match op NAMES at parse (`_check_stages`);
# `REDUCE_SELECT_RULES` (ER1, ER2) matches exact op ids after the endpoint resolves the steps
# (`_plan`).
REDUCER_RULES: Mapping[Reducer, ReducerRule] = MappingProxyType(
    {
        "vote": ReducerRule("answer", "required", "optional", "optional"),
        "median": ReducerRule("answer", "required", "required", "optional", "numeric"),
        "judge": ReducerRule("answer", "forbidden", "forbidden", "forbidden"),
        "pick": ReducerRule("answer", "optional", "optional", "forbidden"),
        "merge": ReducerRule("answer", "optional", "optional", "forbidden"),
        "project": ReducerRule("projection", "optional", "optional", "forbidden"),
        "rank": ReducerRule("selection", "optional", "optional", "forbidden"),
        "concat": ReducerRule("selection", "forbidden", "forbidden", "forbidden"),
        "filter": ReducerRule("selection", "optional", "optional", "forbidden"),
        "mean": ReducerRule("answer", "required", "required", "optional", "numeric"),
    }
)

# WHY by operator NAME (any version): the evidence field a statistic fills (`median` or `mean`)
# follows the reducer, so a statistic op under another reducer writes a wrong record, for example a
# mean into `evidence.median` (review P1 #4, erratum ER7).
_STATISTIC_REDUCERS: Mapping[str, Reducer] = MappingProxyType(
    {
        "median": "median",
        "weighted_median": "median",
        "mean": "mean",
        "weighted_mean": "mean",
    }
)
# The reduce and select op NAMES the mean reducer allows (erd section 2). WHY only mean: it is new
# in E4b, so no spec uses it with other ops. A median spec with a fake reduce op is pinned by the
# stage-rule tests, so the median reducer keeps only the `_STATISTIC_REDUCERS` rule.
_MEAN_OPS: tuple[frozenset[str], frozenset[str]] = (
    frozenset({"mean", "weighted_mean"}),
    frozenset({"value", "nearest"}),
)

# An allow list: the only select op ids a reduce op pairs with. A reduce op not named here pairs
# with any select. After a named reduce op, every select that is not in its list is refused as
# combine_spec_invalid, also a pair that did not crash before: for example weighted_mean@1+top_k@1
# or by_signal@1+all@1 (they failed later at run time, or abstained when no member voted). The
# endpoint checks the list after it resolves the four steps (an unknown operator wins).
# WHY (E4b part 2, review P2 #1, #2): a reduce op with a rule that leaves a member out (erd §6 X1,
# X2) records that member "excluded", and the evidence refuses a chosen excluded member (CE-I3).
# Every such reduce op is named here (the guard test checks it). Its list holds the selects that
# the guard test runs with it and that never chose an excluded member there:
# - filter@1 marks such a member 0, and only kept@1 reads a mark as pass or miss; any other select
#   reads the mark as a score and can choose the member.
# - by_field@1 chooses by the member's own field value and never reads the reduction, so it pairs
#   with no reduce op that leaves a member out.
# - by_signal@1+max_score@1 and weighted_mode@1+first_holder@1 are allowed although the SDK does
#   not emit them: both ran before this rule, and both read only what the reduce step kept
#   (by_signal@1 scores only a member with the signal; the weighted_mode@1 tally holds only a
#   member with a weight), so they cannot choose an excluded member.
# The SDK emits only listed pairs. test_combine_exclusion_never_chosen runs every pairing.
# WHY exact ids, not names: a new version of either op is a new pairing, so it must be listed.
REDUCE_SELECT_RULES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "by_signal@1": frozenset({"best_holder@1", "max_score@1", "top_k@1"}),
        "filter@1": frozenset({"kept@1"}),
        "weighted_mean@1": frozenset({"nearest@1", "value@1"}),
        "weighted_median@1": frozenset({"nearest@1", "value@1"}),
        "weighted_mode@1": frozenset({"first_holder@1", "max_weight_holder@1"}),
    }
)


class _SpecModel(BaseModel):
    """Closed consumer value: any unknown key or loose type is a spec error."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class StepSpec(_SpecModel):
    """One pipeline step: a pinned operator id and its args."""

    op: str = Field(pattern=_OP_ID)
    args: dict[str, Any]


class SignalWeights(_SpecModel):
    """``weights: {"signal": key}``: each member's vote weight comes from the named signal."""

    signal: str

    @field_validator("signal")
    @classmethod
    def _known_signal(cls, value: str) -> str:
        if not (is_signal_key(value) or is_signal_name(value)):
            raise ValueError("weights.signal must be a known signal key or a declared name")
        return value


class VerbalizedSource(_SpecModel):
    """``{"source": "verbalized", "pattern": str, "ignore_case"?: bool}`` (E4b part 3).

    The pattern rules (length, RE2 compile, one group) are the source plugin's; the endpoint checks
    them at plan time through ``registry.source``.
    """

    source: Literal["verbalized"]
    pattern: str
    ignore_case: bool = False


class LogprobSource(_SpecModel):
    """``{"source": "logprob", "form": "mean" | "sum" | "prob"}`` (E4b part 3).

    The value comes from each member's reply log-probabilities (the member reader), not from its
    text.
    """

    source: Literal["logprob"]
    form: Literal["mean", "sum", "prob"]


class EntropySource(_SpecModel):
    """``{"source": "entropy", "top_logprobs": 1..20}`` (E4b part 3).

    The value is the mean token entropy of each member's reply, in nats (the member reader).
    """

    source: Literal["entropy"]
    top_logprobs: int = Field(ge=1, le=20)


class SumSource(_SpecModel):
    """``{"source": "sum", "coefficients": {name: number}}`` (E4b part 6, ans:Q1).

    The value is sum(coefficient x value) over the components, per member. The core computes it
    (``combine/signal_sum.py``), so it has no source plugin.
    """

    source: Literal["sum"]
    coefficients: dict[str, float] = Field(min_length=1, max_length=MAX_DECLARED_SIGNALS - 1)


class ConsistencyMatch(_SpecModel):
    """How a sample is compared with the member's answer (E4b part 7): the E4a stages.

    Both are pinned operator ids, as in the spec's own steps; ``normalize`` may be null.
    """

    extract: StepSpec
    normalize: StepSpec | None


class ConsistencySource(_SpecModel):
    """``{"source": "consistency", "n": 1..32, "temperature": >= 0, "match": {...}}`` (E4b part 7).

    The value is the fraction of a member's ``n`` extra calls (the context ``samples``) whose
    answer matches the member's answer after ``match``. Every key is required.
    """

    source: Literal["consistency"]
    n: int = Field(ge=1, le=32)
    temperature: float = Field(ge=0)
    match: ConsistencyMatch


# WHY a tagged union: the `source` word picks the one model, so a bad entry fails on its own keys.
DeclaredSource = Annotated[
    VerbalizedSource | LogprobSource | EntropySource | SumSource | ConsistencySource,
    Field(discriminator="source"),
]


class GateSpec(_SpecModel):
    """``gate``: keep the majority when ``observe cmp threshold`` holds (E4b part 5).

    ``otherwise`` names the fallback that answers when the comparison is false. The fallback call
    itself is in the url4, not in the spec.
    """

    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: GateOtherwise
    # E4b part 6 (ans:Q2): the closed band [lo, hi] in which the Case abstains instead of comparing.
    # WHY a comment and not a docstring line: the class docstring is the schema ``description``,
    # and the pinned spec v1 snapshot keeps that text.
    abstain_band: list[float] | None = Field(default=None, min_length=2, max_length=2)


class CombineSpec(_SpecModel):
    """``screamingface.combine-spec.v1``: every key required, ``null`` only where typed."""

    schema_id: Literal["screamingface.combine-spec.v1"] = Field(alias="schema")
    reducer: Reducer
    members: list[str] = Field(min_length=1)
    extract: StepSpec | None
    normalize: StepSpec | None
    reduce: StepSpec
    select: StepSpec
    weights: dict[str, float] | SignalWeights | None
    signals: dict[str, DeclaredSource] | None = None
    gate: GateSpec | None = None

    @field_validator("signals", mode="wrap")
    @classmethod
    def _quiet_signals(cls, value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        # WHY: a nested error's location holds the declared name; a failure names rules only.
        try:
            return handler(value)
        except ValidationError:
            raise ValueError("signals must map declared names to known sources") from None

    @field_validator("gate", mode="wrap")
    @classmethod
    def _quiet_gate(cls, value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        # WHY: a nested error's location or input can hold a gate value; a failure names rules.
        try:
            return handler(value)
        except ValidationError:
            raise ValueError("gate must be a valid gate object") from None

    @model_validator(mode="after")
    def _check(self) -> CombineSpec:
        _check_members(self.members)
        _check_weights(self.weights, self.members)
        _check_stages(self)
        _check_signals(self)
        _check_gate(self)
        return self


def _check_signals(spec: CombineSpec) -> None:
    if "signals" not in spec.model_fields_set:
        return
    signals = spec.signals
    # WHY an explicit null is refused although the schema types it: no declaration omits the key.
    if signals is None or not 1 <= len(signals) <= MAX_DECLARED_SIGNALS:
        raise ValueError(f"signals must declare 1 to {MAX_DECLARED_SIGNALS} names")
    if not all(is_signal_name(name) for name in signals):
        raise ValueError("signals has a name that is not a declared signal name")
    # WHY at most one (C1): every member call asks for one `top_logprobs`, so two entropy sources
    # could not each get the k they declare.
    if sum(isinstance(entry, EntropySource) for entry in signals.values()) > 1:
        raise ValueError("signals declares more than one entropy source")
    # E4b part 7 (P4): one sample panel per member, so one consistency source per spec.
    if sum(isinstance(entry, ConsistencySource) for entry in signals.values()) > 1:
        raise ValueError("signals declares at most one consistency source")
    for entry in signals.values():
        if isinstance(entry, SumSource):  # E4b part 6
            _check_sum(entry, signals)
    _check_weight_source(spec.weights, signals)


def _check_weight_source(
    weights: dict[str, float] | SignalWeights | None, signals: Mapping[str, DeclaredSource]
) -> None:
    """A vote weight must be able to be greater than 0 (P14, LP-E1, EN-E2), as in the SDK.

    WHY: a log-probability (``mean``, ``sum``) is at most 0, and a higher entropy means LESS
    confidence; only ``logprob`` in the form ``prob`` is a probability. A sum that adds such a
    source is not a weight either (E4b part 6 P13, SA-E4; the SDK ``sf.Fusion`` rule).
    """
    if not isinstance(weights, SignalWeights):
        return
    source = signals.get(weights.signal)
    if _cannot_weigh(source):
        raise ValueError("weights.signal must not be an entropy or a non-prob logprob source")
    if isinstance(source, SumSource) and any(
        _cannot_weigh(signals.get(name)) for name in source.coefficients
    ):
        raise ValueError(
            "weights.signal must not be a sum that adds an entropy or a non-prob logprob source"
        )


def _cannot_weigh(source: DeclaredSource | None) -> bool:
    """Whether a declared source can never give a weight greater than 0 (P14)."""
    return isinstance(source, EntropySource) or (
        isinstance(source, LogprobSource) and source.form != "prob"
    )


def _check_sum(entry: SumSource, signals: Mapping[str, DeclaredSource]) -> None:
    """SU-I1, SU-I2 and the non-zero rule (E4b part 6, P3, P4). A message names the rule only."""
    for name, coefficient in entry.coefficients.items():
        if name not in signals:
            raise ValueError("a sum adds only names the spec declares")
        if isinstance(signals[name], SumSource):
            raise ValueError("a sum does not add another sum")
        if coefficient == 0:
            raise ValueError("a sum coefficient is not zero")  # 0.0 == -0.0, so both fail


def _check_gate(spec: CombineSpec) -> None:
    if "gate" not in spec.model_fields_set:
        return
    gate = spec.gate
    # WHY an explicit null is refused although the schema types it: as for ``signals``.
    if gate is None:
        raise ValueError("gate must be an object when present")
    if spec.reducer != "vote":
        raise ValueError("only a vote takes a gate")
    if GATE_OBSERVE.fullmatch(gate.observe) is None:
        raise ValueError("gate observe must be agreement, chosen:<name> or mean:<name>")
    if gate.observe == "agreement":
        _check_agreement_gate(gate)
    elif gate.observe.partition(":")[2] not in (spec.signals or {}):
        raise ValueError("gate reads a name the spec does not declare")
    _check_band(gate)


def _check_agreement_gate(gate: GateSpec) -> None:
    if gate.cmp not in (">=", ">"):
        raise ValueError("an agreement gate compares with >= or >")
    if not 0 <= gate.threshold <= 1:
        raise ValueError("an agreement gate threshold is between 0 and 1")


def _check_band(gate: GateSpec) -> None:
    """The ``abstain_band`` rules (E4b part 6, P7). Each message names a rule, never a value.

    The model already holds two finite floats (strict, ``allow_inf_nan=False``); a list that is not
    two numbers fails inside ``GateSpec`` with the quiet ``gate`` message.
    """
    # WHY the guard here and not in ``_check_gate``: that function is at the branch limit.
    if "abstain_band" not in gate.model_fields_set:
        return
    band = gate.abstain_band
    # WHY an explicit null is refused although the schema types it: as for ``signals``.
    if band is None:
        raise ValueError("gate abstain_band must be a pair when present")
    low, high = band
    if low > high:
        raise ValueError("a gate abstain_band needs lo <= hi")
    if gate.observe == "agreement" and not 0 <= low <= high <= 1:
        raise ValueError("an agreement gate abstain_band is between 0 and 1")


def _check_members(members: list[str]) -> None:
    if len(set(members)) != len(members):
        raise ValueError("members must be unique")
    if not all(_MEMBER.fullmatch(member) for member in members):
        raise ValueError("members must be named member_1, member_2, ...")


def _check_weights(weights: dict[str, float] | SignalWeights | None, members: list[str]) -> None:
    if weights is None or isinstance(weights, SignalWeights):
        return
    if set(weights) != set(members):
        raise ValueError("weights must name exactly the members")
    if not all(0 < weight <= MAX_WEIGHT for weight in weights.values()):
        raise ValueError("weights must be greater than zero and at most the weight cap")


def _check_presence(name: str, presence: Presence, present: bool, reducer: str) -> None:
    if presence == "required" and not present:
        raise ValueError(f"reducer {reducer} requires {name}")
    if presence == "forbidden" and present:
        raise ValueError(f"reducer {reducer} forbids {name}")


def _check_stages(spec: CombineSpec) -> None:
    rule = REDUCER_RULES[spec.reducer]
    _check_presence("extract", rule.extract, spec.extract is not None, spec.reducer)
    _check_presence("normalize", rule.normalize, spec.normalize is not None, spec.reducer)
    _check_presence("weights", rule.weights, spec.weights is not None, spec.reducer)
    if spec.normalize is not None and spec.extract is None:
        raise ValueError("normalize needs extract")
    if rule.normalize_name is not None and spec.normalize is not None:
        _check_normalize_name(spec.normalize, rule.normalize_name, spec.reducer)
    _check_statistic_reducer(spec.reduce, spec.reducer)
    if spec.reducer == "mean":
        _check_mean_ops(spec.reduce, spec.select)


def _check_normalize_name(normalize: StepSpec, name: str, reducer: str) -> None:
    # WHY by NAME, any version: the reducer reads its values in the family that name stands for
    # (a median reads decimals, so only the numeric normalizer makes them decimals). The message
    # names the rule, not the offending id.
    if normalize.op.partition("@")[0] != name:
        raise ValueError(f"reducer {reducer} requires a {name} normalize step")


def _check_statistic_reducer(reduce: StepSpec, reducer: str) -> None:
    # The message names the rule, not the offending id.
    owner = _STATISTIC_REDUCERS.get(reduce.op.partition("@")[0])
    if owner is not None and owner != reducer:
        raise ValueError(f"reducer {reducer} forbids this statistic reduce step")


def _check_mean_ops(reduce: StepSpec, select: StepSpec) -> None:
    # The messages name the rule, not the offending ids.
    reduces, selects = _MEAN_OPS
    if reduce.op.partition("@")[0] not in reduces:
        raise ValueError("reducer mean requires a mean or weighted_mean reduce step")
    if select.op.partition("@")[0] not in selects:
        raise ValueError("reducer mean requires a value or nearest select step")


def declares_reply_sources(spec: CombineSpec) -> bool:
    """Whether the spec declares a logprob or entropy source: its context then carries
    ``sources`` (erd §4), so the member reader can find each member's reply numbers."""
    signals = spec.signals or {}
    return any(isinstance(entry, LogprobSource | EntropySource) for entry in signals.values())


def declares_consistency(spec: CombineSpec) -> tuple[str, ConsistencySource] | None:
    """The name and the one consistency source of the spec (E4b part 7), or None.

    Its context then carries ``samples`` (erd §4); ``_check_signals`` allows at most one.
    The endpoint uses ``_sample_item(plan)`` instead; this function stays for its tests.
    """
    for name, entry in (spec.signals or {}).items():
        if isinstance(entry, ConsistencySource):
            return name, entry
    return None


def parse_spec(intent: str) -> CombineSpec:
    """Parse the combine intent; a failure never repeats a value from the text."""
    try:
        decoded = loads_bounded(intent, unique_keys=True)
    except ValueError as exc:
        raise SpecInvalid("combine spec is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SpecInvalid("combine spec must be a JSON object")
    try:
        return CombineSpec.model_validate(decoded)
    except ValidationError as exc:
        raise SpecInvalid(f"combine spec is invalid: {_describe(exc)}") from exc


def _clip(part: object) -> str:
    text = str(part)
    return text if len(text) <= _MAX_LOCATION_CHARS else text[:_MAX_LOCATION_CHARS] + "\u2026"


def _describe(exc: ValidationError) -> str:
    # WHY loc + msg only: pydantic messages carry the rule that failed, and the ``input`` key of an
    # error (the offending value) is the one part that could echo an arg or a member name. A key
    # of the spec can be any length, so each location part is cut to keep the message short.
    parts = sorted(
        {f"{'.'.join(map(_clip, e['loc'])) or 'spec'}: {e['msg']}" for e in exc.errors()}
    )
    return "; ".join(parts[:_MAX_ERRORS_SHOWN])


@dataclass(frozen=True, slots=True)
class CombineContext:
    """The decoded context: the question, the members' texts, and the declared signals.

    ``outputs`` names every member, except when the context is a quorum ``panel``: then it names
    only the members that answered (OME-1557).
    ``samples`` (E4b part 7): each member's sample texts in j order, present exactly when the spec
    declares consistency.
    """

    input: str
    outputs: Mapping[str, str]
    signals: Mapping[str, str]
    sources: MemberSources | None = None
    samples: Mapping[str, tuple[str, ...]] | None = None


def canonical_params(pairs: Iterable[tuple[str, str]]) -> str:
    """The one text form of a call's params: sorted pairs, each percent-encoded, joined by ``&``.

    INVARIANT: the SDK builds ``sources[...].params`` with this very expression (SDK unit 7), and
    ``parse_context`` accepts only text that equals it, so a fingerprint has exactly one spelling.
    """
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(pairs))


def parse_context(
    context: str,
    members: Sequence[str],
    *,
    sources_expected: bool = False,
    samples_n: int | None = None,
) -> CombineContext:
    """Parse the combine context against the spec's members.

    The members arrive as ``outputs`` (every member) or as a quorum ``panel`` (the members that
    answered), never both. ``sources`` must be present exactly when the spec reads an accounting
    signal. ``samples`` must be present exactly when ``samples_n`` (the declared consistency
    ``n``, E4b part 7) is not None.
    """
    try:
        decoded = loads_bounded(context, unique_keys=True)
    except ValueError as exc:
        raise SpecInvalid("combine context is not valid JSON") from exc
    if (
        not isinstance(decoded, dict)
        or "input" not in decoded
        or not decoded.keys() <= _CONTEXT_KEYS
        or ("outputs" in decoded) == ("panel" in decoded)
    ):
        raise SpecInvalid("combine context has the wrong shape")
    question = decoded["input"]
    outputs = _member_outputs(decoded, members)
    signals = _text_map(decoded.get("signals", {}))
    if not isinstance(question, str):
        raise SpecInvalid("combine context has the wrong shape")
    if not all(_SIGNAL.fullmatch(name) for name in signals):
        raise SpecInvalid("combine context has an invalid signal name")
    if ("sources" in decoded) != sources_expected:
        raise SpecInvalid(
            "combine context sources are present exactly when the spec reads an accounting signal"
        )
    sources = _parse_sources(decoded["sources"], members) if sources_expected else None
    if ("samples" in decoded) != (samples_n is not None):
        raise SpecInvalid(
            "combine context samples are present exactly when the spec declares consistency"
        )
    samples = None if samples_n is None else _parse_samples(decoded["samples"], members, samples_n)
    return CombineContext(
        question, MappingProxyType(outputs), MappingProxyType(signals), sources, samples
    )


def _parse_samples(
    value: object, members: Sequence[str], samples_n: int
) -> Mapping[str, tuple[str, ...]]:
    """``{member: rows text}`` with every member named; each member's sample texts in j order.

    The rows are url4's broadcast rows of the member's sample panel: slot ``sample_j`` at position
    j, for j in 1..samples_n. A failed sample is left out by url4, so a member may have fewer rows.
    """
    texts = _text_map(value)
    if set(texts) != set(members):
        raise SpecInvalid("combine context samples do not match the spec members")
    names = [f"sample_{index}" for index in range(1, samples_n + 1)]
    parsed: dict[str, tuple[str, ...]] = {}
    for member in members:
        rows = _panel_rows(
            texts[member],
            names,
            what="samples",
            mismatch="combine context samples do not match the sample slots",
        )
        parsed[member] = tuple(rows[name] for name in names if name in rows)
    return MappingProxyType(parsed)


def _parse_sources(value: object, members: Sequence[str]) -> MemberSources:
    """``{member: {call_key: {"path": str, "params": canonical text}}}`` with every member named."""
    if not isinstance(value, dict) or set(value) != set(members):
        raise SpecInvalid("combine context sources do not match the spec members")
    parsed: dict[str, Mapping[str, CallFingerprint]] = {}
    for member, calls in value.items():
        if not isinstance(calls, dict):
            raise SpecInvalid("combine context sources have the wrong shape")
        parsed[member] = MappingProxyType(
            {key: _parse_call(key, entry) for key, entry in calls.items()}
        )
    return MappingProxyType(parsed)


def _parse_call(key: str, entry: object) -> CallFingerprint:
    if (
        _CALL_KEY.fullmatch(key) is None
        or not isinstance(entry, dict)
        or set(entry) != {"path", "params"}
    ):
        raise SpecInvalid("combine context sources have the wrong shape")
    path, params = entry["path"], entry["params"]
    if not isinstance(path, str) or not path or not isinstance(params, str):
        raise SpecInvalid("combine context sources have the wrong shape")
    return path, _decode_params(params)


def _decode_params(text: str) -> tuple[tuple[str, str], ...]:
    """The pairs of a canonical params text; anything that is not canonical is ``SpecInvalid``."""
    if text == "":
        return ()
    pairs: list[tuple[str, str]] = []
    try:
        for part in text.split("&"):
            raw_key, separator, raw_value = part.partition("=")
            if not separator:
                raise SpecInvalid("combine context sources params are not canonical")
            pairs.append((unquote(raw_key, errors="strict"), unquote(raw_value, errors="strict")))
    except UnicodeDecodeError as exc:
        raise SpecInvalid("combine context sources params are not canonical") from exc
    names = [name for name, _ in pairs]
    if "" in names or len(set(names)) != len(names) or canonical_params(pairs) != text:
        raise SpecInvalid("combine context sources params are not canonical")
    return tuple(pairs)


def _member_outputs(decoded: Mapping[str, object], members: Sequence[str]) -> dict[str, str]:
    """Every member's text from ``outputs``, or the answering members' texts from ``panel``."""
    if "panel" in decoded:
        return _panel_outputs(decoded["panel"], members)
    outputs = _text_map(decoded["outputs"])
    if len(outputs) != len(members) or set(outputs) != set(members):
        raise SpecInvalid("combine context outputs do not match the spec members")
    return outputs


def _panel_outputs(value: object, members: Sequence[str]) -> dict[str, str]:
    """The texts of a quorum panel: url4's broadcast rows, one per member that answered.

    url4 leaves out an optional member that failed and checks the quorum before this call runs
    (OME-1557), so an absent member is not an error here.
    """
    return _panel_rows(
        value,
        members,
        what="panel",
        mismatch="combine context panel does not match the spec members",
    )


def _panel_rows(value: object, names: Sequence[str], *, what: str, mismatch: str) -> dict[str, str]:
    """url4 broadcast rows keyed by name; ``names[i]`` sits at position ``i + 1`` (CX-I2, OME-1557).

    A row is ``{"source_position": i, "source_name": names[i - 1], "result": text}``. A name may
    be absent (url4 leaves out a failed optional slot). Any other shape is an error, with a fixed
    message that never holds a text: the rows are url4's own output. The quorum panel and the
    consistency samples (E4b part 7) share this one row contract.
    """
    if not isinstance(value, str):
        raise SpecInvalid(f"combine context {what} has the wrong shape")
    try:
        rows = loads_bounded(value, unique_keys=True)
    except ValueError as exc:
        raise SpecInvalid(f"combine context {what} is not valid JSON") from exc
    if not isinstance(rows, list):
        raise SpecInvalid(f"combine context {what} has the wrong shape")
    positions = {name: index for index, name in enumerate(names, 1)}
    texts: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _PANEL_ROW_KEYS:
            raise SpecInvalid(f"combine context {what} has the wrong shape")
        name, position, text = row["source_name"], row["source_position"], row["result"]
        if (
            not isinstance(name, str)
            or name in texts
            or type(position) is not int
            or positions.get(name) != position
            or not isinstance(text, str)
        ):
            raise SpecInvalid(mismatch)
        texts[name] = text
    return texts


def _text_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(text, str) for key, text in value.items()
    ):
        raise SpecInvalid("combine context has the wrong shape")
    return dict(value)


__all__ = [
    "COMBINE_SPEC_SCHEMA",
    "FALLBACK_JUDGE",
    "FALLBACK_WRITER",
    "MAX_MEMBERS",
    "MAX_WEIGHT",
    "REDUCER_RULES",
    "REDUCE_SELECT_RULES",
    "CombineContext",
    "CombineSpec",
    "ConsistencyMatch",
    "ConsistencySource",
    "DeclaredSource",
    "EntropySource",
    "GateSpec",
    "LogprobSource",
    "Presence",
    "ReducerRule",
    "SignalWeights",
    "StepSpec",
    "SumSource",
    "VerbalizedSource",
    "canonical_params",
    "declares_consistency",
    "declares_reply_sources",
    "parse_context",
    "parse_spec",
]
