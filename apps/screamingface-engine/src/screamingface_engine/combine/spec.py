"""The strict parsers of a combine call's two payloads (OME-1289 E4a).

FEATURE: read the spec (``screamingface.combine-spec.v1``, the url4 ``intent``) and the context
(the member outputs and signals) of one combine call, and reject anything off-contract.
STORY: as the endpoint, I get a typed spec and context or a ``SpecInvalid`` -- never a half-read
payload, and never an error message that repeats what a member or a judge wrote.

INVARIANT: every key of the spec is always present except the optional ``signals`` (E4b part 3);
``null`` is allowed only where the type says so. Unknown keys, duplicate JSON keys,
NaN/Infinity and nesting beyond 64 levels are rejected.
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
    MAX_DECLARED_SIGNALS,
    CallFingerprint,
    EvidenceKind,
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
# WHY "writer_" and not "writer.": the SDK builds the context with url4 struct, whose keys are
# [A-Za-z0-9_]+ only, so a dotted signal key cannot be written (OME-1289 unit 8-10 spec, P1).
_SIGNAL = re.compile(r"judge|writer_[A-Za-z_][A-Za-z0-9_]*")
_CONTEXT_KEYS = frozenset({"input", "outputs", "panel", "signals", "sources"})
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


# WHY a tagged union: the `source` word picks the one model, so a bad entry fails on its own keys.
DeclaredSource = Annotated[
    VerbalizedSource | LogprobSource | EntropySource, Field(discriminator="source")
]


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

    @field_validator("signals", mode="wrap")
    @classmethod
    def _quiet_signals(cls, value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        # WHY: a nested error's location holds the declared name; a failure names rules only.
        try:
            return handler(value)
        except ValidationError:
            raise ValueError("signals must map declared names to known sources") from None

    @model_validator(mode="after")
    def _check(self) -> CombineSpec:
        _check_members(self.members)
        _check_weights(self.weights, self.members)
        _check_stages(self)
        _check_signals(self)
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
    _check_weight_source(spec.weights, signals)


def _check_weight_source(
    weights: dict[str, float] | SignalWeights | None, signals: Mapping[str, DeclaredSource]
) -> None:
    """A vote weight must be able to be greater than 0 (P14, LP-E1, EN-E2), as in the SDK.

    WHY: a log-probability (``mean``, ``sum``) is at most 0, and a higher entropy means LESS
    confidence; only ``logprob`` in the form ``prob`` is a probability.
    """
    if not isinstance(weights, SignalWeights):
        return
    source = signals.get(weights.signal)
    if isinstance(source, EntropySource) or (
        isinstance(source, LogprobSource) and source.form != "prob"
    ):
        raise ValueError("weights.signal must not be an entropy or a non-prob logprob source")


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
    """

    input: str
    outputs: Mapping[str, str]
    signals: Mapping[str, str]
    sources: MemberSources | None = None


def canonical_params(pairs: Iterable[tuple[str, str]]) -> str:
    """The one text form of a call's params: sorted pairs, each percent-encoded, joined by ``&``.

    INVARIANT: the SDK builds ``sources[...].params`` with this very expression (SDK unit 7), and
    ``parse_context`` accepts only text that equals it, so a fingerprint has exactly one spelling.
    """
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(pairs))


def parse_context(
    context: str, members: Sequence[str], *, sources_expected: bool = False
) -> CombineContext:
    """Parse the combine context against the spec's members.

    The members arrive as ``outputs`` (every member) or as a quorum ``panel`` (the members that
    answered), never both. ``sources`` must be present exactly when the spec reads an accounting
    signal.
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
    return CombineContext(question, MappingProxyType(outputs), MappingProxyType(signals), sources)


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

    A row is ``{"source_position": i, "source_name": "member_i", "result": text}``. url4 leaves
    out an optional member that failed and checks the quorum before this call runs (OME-1557), so
    an absent member is not an error here. Any other shape is: the rows are url4's own output.
    """
    if not isinstance(value, str):
        raise SpecInvalid("combine context panel has the wrong shape")
    try:
        rows = loads_bounded(value, unique_keys=True)
    except ValueError as exc:
        raise SpecInvalid("combine context panel is not valid JSON") from exc
    if not isinstance(rows, list):
        raise SpecInvalid("combine context panel has the wrong shape")
    positions = {member: index for index, member in enumerate(members, 1)}
    outputs: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _PANEL_ROW_KEYS:
            raise SpecInvalid("combine context panel has the wrong shape")
        name, position, text = row["source_name"], row["source_position"], row["result"]
        if (
            not isinstance(name, str)
            or name in outputs
            or type(position) is not int
            or positions.get(name) != position
            or not isinstance(text, str)
        ):
            raise SpecInvalid("combine context panel does not match the spec members")
        outputs[name] = text
    return outputs


def _text_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(text, str) for key, text in value.items()
    ):
        raise SpecInvalid("combine context has the wrong shape")
    return dict(value)


__all__ = [
    "COMBINE_SPEC_SCHEMA",
    "MAX_MEMBERS",
    "MAX_WEIGHT",
    "REDUCER_RULES",
    "REDUCE_SELECT_RULES",
    "CombineContext",
    "CombineSpec",
    "DeclaredSource",
    "EntropySource",
    "LogprobSource",
    "Presence",
    "ReducerRule",
    "SignalWeights",
    "StepSpec",
    "VerbalizedSource",
    "canonical_params",
    "declares_reply_sources",
    "parse_context",
    "parse_spec",
]
