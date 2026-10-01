"""The strict parsers of a combine call's two payloads (OME-1289 E4a).

FEATURE: read the spec (``screamingface.combine-spec.v1``, the url4 ``intent``) and the context
(the member outputs and signals) of one combine call, and reject anything off-contract.
STORY: as the endpoint, I get a typed spec and context or a ``SpecInvalid`` -- never a half-read
payload, and never an error message that repeats what a member or a judge wrote.

INVARIANT: every key of the spec is always present; ``null`` is allowed only where the type says
so. Unknown keys, duplicate JSON keys, NaN/Infinity and nesting beyond 64 levels are rejected.
INVARIANT: a failure message names locations and rules, never input values.
The spec text is the SDK's canonical JSON with ``$`` written as ``\\u0024``; ``json.loads`` gives
the ``$`` back, so this parser needs no url4 escape handling.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from screamingface_engine.combine.ports import (
    EvidenceKind,
    Reducer,
    SpecInvalid,
    loads_bounded,
)

COMBINE_SPEC_SCHEMA = "screamingface.combine-spec.v1"
_OP_ID = r"^[a-z][a-z0-9_]{0,47}@[1-9][0-9]{0,5}$"
_MEMBER = re.compile(r"member_[1-9][0-9]*")
# WHY "writer_" and not "writer.": the SDK builds the context with url4 struct, whose keys are
# [A-Za-z0-9_]+ only, so a dotted signal key cannot be written (OME-1289 unit 8-10 spec, P1).
_SIGNAL = re.compile(r"judge|writer_[A-Za-z_][A-Za-z0-9_]*")
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
    None for any. This is the ONLY per-reducer operator rule; later units add none.
    """

    kind: EvidenceKind
    extract: Presence
    normalize: Presence
    weights: Presence
    normalize_name: str | None = None


# Global rule (also checked below): normalize present => extract present.
# AIDEV-NOTE: units 8-10 may tighten the rows of their own reducers (never add an operator rule).
REDUCER_RULES: Mapping[Reducer, ReducerRule] = MappingProxyType(
    {
        "vote": ReducerRule("answer", "required", "optional", "optional"),
        "median": ReducerRule("answer", "required", "required", "forbidden", "numeric"),
        "judge": ReducerRule("answer", "forbidden", "forbidden", "forbidden"),
        "pick": ReducerRule("answer", "required", "optional", "forbidden"),
        "merge": ReducerRule("answer", "optional", "optional", "forbidden"),
        "project": ReducerRule("projection", "optional", "optional", "forbidden"),
        "rank": ReducerRule("selection", "optional", "optional", "forbidden"),
        "concat": ReducerRule("selection", "forbidden", "forbidden", "forbidden"),
    }
)


class _SpecModel(BaseModel):
    """Closed consumer value: any unknown key or loose type is a spec error."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class StepSpec(_SpecModel):
    """One pipeline step: a pinned operator id and its args."""

    op: str = Field(pattern=_OP_ID)
    args: dict[str, Any]


class CombineSpec(_SpecModel):
    """``screamingface.combine-spec.v1``: every key required, ``null`` only where typed."""

    schema_id: Literal["screamingface.combine-spec.v1"] = Field(alias="schema")
    reducer: Reducer
    members: list[str] = Field(min_length=1)
    extract: StepSpec | None
    normalize: StepSpec | None
    reduce: StepSpec
    select: StepSpec
    weights: dict[str, float] | None

    @model_validator(mode="after")
    def _check(self) -> CombineSpec:
        _check_members(self.members)
        _check_weights(self.weights, self.members)
        _check_stages(self)
        return self


def _check_members(members: list[str]) -> None:
    if len(set(members)) != len(members):
        raise ValueError("members must be unique")
    if not all(_MEMBER.fullmatch(member) for member in members):
        raise ValueError("members must be named member_1, member_2, ...")


def _check_weights(weights: dict[str, float] | None, members: list[str]) -> None:
    if weights is None:
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


def _check_normalize_name(normalize: StepSpec, name: str, reducer: str) -> None:
    # WHY by NAME, any version: the reducer reads its values in the family that name stands for
    # (a median reads decimals, so only the numeric normalizer makes them decimals). The message
    # names the rule, not the offending id.
    if normalize.op.partition("@")[0] != name:
        raise ValueError(f"reducer {reducer} requires a {name} normalize step")


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
    """The decoded context: the question, every member's text, and the declared signals."""

    input: str
    outputs: Mapping[str, str]
    signals: Mapping[str, str]


def parse_context(context: str, members: Sequence[str]) -> CombineContext:
    """Parse the combine context against the spec's members."""
    try:
        decoded = loads_bounded(context, unique_keys=True)
    except ValueError as exc:
        raise SpecInvalid("combine context is not valid JSON") from exc
    if not isinstance(decoded, dict) or not {"input", "outputs"} <= decoded.keys() <= {
        "input",
        "outputs",
        "signals",
    }:
        raise SpecInvalid("combine context has the wrong shape")
    question = decoded["input"]
    outputs = _text_map(decoded["outputs"])
    signals = _text_map(decoded.get("signals", {}))
    if not isinstance(question, str):
        raise SpecInvalid("combine context has the wrong shape")
    if len(outputs) != len(members) or set(outputs) != set(members):
        raise SpecInvalid("combine context outputs do not match the spec members")
    if not all(_SIGNAL.fullmatch(name) for name in signals):
        raise SpecInvalid("combine context has an invalid signal name")
    return CombineContext(question, MappingProxyType(outputs), MappingProxyType(signals))


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
    "CombineContext",
    "CombineSpec",
    "Presence",
    "ReducerRule",
    "StepSpec",
    "parse_context",
    "parse_spec",
]
