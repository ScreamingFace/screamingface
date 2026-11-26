"""The Router vocabulary C2 and C5 share: strict JSON, field rules, the policy and evidence.

FEATURE: Router Recipe extension (Unit 5.2). `world.router_spec` reads the C2 definition and
`router_decision` reads the C5 draft and record; both take their labels, policy and strict JSON
reader from here, so the two contracts cannot drift apart.

WHY a shared leaf: `router_decision` is a shared leaf (see its WHY), and what it reads must be one.
INVARIANT: every record here is closed: unknown keys, wrong types and non-finite numbers are
refused, never coerced.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Collection, Sequence
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from screamingface_engine.combine.ports import utf8_exceeds

SCORES_CONTRACT = "classification-scores-v1"
MAX_LABEL_BYTES = 64
MAX_UNKNOWN_CHARS = 64
MAX_UNKNOWN_LABELS = 32

Parse = Literal["ok", "no_match", "unrecognized", "unparsed"]

CODE = re.compile(r"[a-z][a-z0-9_.]{0,63}")
"""A bounded failure code: 1-64 of a-z, 0-9, `_` and `.`, from a letter."""
_ROUTER = re.compile(r"router_[1-9][0-9]*")
_REVISION = re.compile(r"sha256:[0-9a-f]{64}")
_CALL_BINDING = re.compile(r"(?:router|selector|model|synthesis)_[1-9][0-9]*")


# --- strict JSON ------------------------------------------------------------------------------


def _no_constant(name: str) -> object:
    raise ValueError("a JSON constant is not a number")


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("a JSON number is not finite")
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded = dict(pairs)
    if len(decoded) != len(pairs):
        raise ValueError("a JSON object repeats a key")
    return decoded


def strict_json(text: str) -> object:
    """Decode a strict record: no NaN/Infinity, no non-finite number, no repeated key.

    Raises:
        ValueError: the text is not strict JSON.
    """

    try:
        return json.loads(
            text, parse_constant=_no_constant, parse_float=_finite, object_pairs_hook=_unique
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc


def field_rule(exc: ValidationError, masked: frozenset[str] = frozenset()) -> str:
    """The first failing field path and its rule, never the input value.

    INVARIANT: a refusal never echoes input. A key of a map named in ``masked`` is authored text,
    so it shows as ``<key>``.
    """

    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    if not errors:
        return "the root"
    first = errors[0]
    parts: list[str] = []
    for part in first["loc"]:
        parts.append("<key>" if parts and parts[-1] in masked else str(part))
    path = ".".join(parts) or "the root"
    if first["type"] == "value_error":
        return f"{path} ({first['msg'].removeprefix('Value error, ')})"
    return f"{path} ({first['type']})"


# --- field rules --------------------------------------------------------------------------------


def _label(value: str) -> str:
    if (
        not value
        or utf8_exceeds(value, MAX_LABEL_BYTES)
        or any(unicodedata.category(char) in ("Cc", "Cs") for char in value)
    ):
        raise ValueError("a label is 1-64 UTF-8 bytes with no control character")
    return value


def _matches(pattern: re.Pattern[str], rule: str) -> AfterValidator:
    def check(value: str) -> str:
        if pattern.fullmatch(value) is None:
            raise ValueError(rule)
        return value

    return AfterValidator(check)


Label = Annotated[str, AfterValidator(_label)]
Code = Annotated[str, _matches(CODE, "a code is 1-64 of a-z, 0-9, _ and . from a letter")]
RouterBinding = Annotated[str, _matches(_ROUTER, "a router binding is router_N")]
Revision = Annotated[str, _matches(_REVISION, "a revision is sha256:<64 hex>")]
CallBinding = Annotated[str, _matches(_CALL_BINDING, "a call binding is <role>_N")]
UnknownLabel = Annotated[str, Field(min_length=1, max_length=MAX_UNKNOWN_CHARS)]
Index = Annotated[int, Field(ge=0)]
Count = Annotated[int, Field(ge=0)]
ModelId = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class RouterPolicy(StrictModel):
    """The C2 `router-policy` record."""

    type: Literal["router-policy"]
    # WHY an int bound and not Literal[1]: a JSON literal 1 accepts `true`.
    version: Annotated[int, Field(ge=1, le=1)]
    match: Literal["best", "exact"]
    select: Literal["one", "all"]


# --- evidence -----------------------------------------------------------------------------------


class ScoreRow(StrictModel):
    label: Label
    score: Annotated[float, Field(ge=0, le=1)]


class ScoringRecord(StrictModel):
    source: Literal["scoring"]
    model: ModelId
    contract: Literal["classification-scores-v1"]
    scores: tuple[ScoreRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct(self) -> ScoringRecord:
        labels = [row.label for row in self.scores]
        if len(set(labels)) != len(labels):
            raise ValueError("scores name each label once")
        return self


class SelectorRecord(StrictModel):
    source: Literal["llm", "regex"]
    labels: tuple[Label, ...] = Field(max_length=MAX_UNKNOWN_LABELS)
    unknown: tuple[UnknownLabel, ...] = Field(max_length=MAX_UNKNOWN_LABELS)
    parse: Parse

    @model_validator(mode="after")
    def _producible(self) -> SelectorRecord:
        """The evidence is one its source can produce (C5 evidence forms)."""
        labels, unknown, parse = self.labels, self.unknown, self.parse
        allowed = (
            ("ok", "no_match") if self.source == "regex" else ("ok", "unrecognized", "unparsed")
        )
        if parse not in allowed:
            raise ValueError("parse is one the source writes")
        if len(set(labels)) != len(labels) or len(set(unknown)) != len(unknown):
            raise ValueError("labels and unknown name each token once")
        if parse != "unrecognized" and unknown:
            raise ValueError("only an unrecognized reply keeps unknown tokens")
        if (parse == "ok") != bool(labels) and parse != "unrecognized":
            raise ValueError("ok names a label; no_match and unparsed name none")
        if parse == "unrecognized" and not unknown:
            raise ValueError("an unrecognized reply keeps its unknown tokens")
        return self


Evidence = Annotated[ScoringRecord | SelectorRecord, Field(discriminator="source")]


# --- the C6 reason an evidence gives ------------------------------------------------------------

Reason = Literal[
    "unique_max", "exact", "tie", "empty", "unknown_only", "unknown_selected", "multiple_selected"
]


def best_reason(scores: Sequence[tuple[str, float]], unknown: Collection[str]) -> Reason:
    """C6 ``best``: a unique maximum selects (``unique_max``) unless its label has no candidate.

    INVARIANT: never sorts or promotes a runner-up; the scores are a complete vector.
    """
    top = max(score for _, score in scores)
    leaders = [label for label, score in scores if score == top]
    if len(leaders) > 1:
        return "tie"
    return "unknown_selected" if leaders[0] in unknown else "unique_max"


def exact_reason(select: Literal["one", "all"], parse: Parse, recognized: int) -> Reason:
    """C6 ``exact``: ``exact`` selects the recognized labels; any other reason falls back."""
    if parse in ("no_match", "unparsed"):
        return "empty"
    if recognized:
        return "multiple_selected" if select == "one" and recognized > 1 else "exact"
    return "unknown_selected" if select == "one" else "unknown_only"


__all__ = [
    "CODE",
    "MAX_LABEL_BYTES",
    "MAX_UNKNOWN_CHARS",
    "MAX_UNKNOWN_LABELS",
    "SCORES_CONTRACT",
    "CallBinding",
    "Code",
    "Count",
    "Evidence",
    "Index",
    "Label",
    "ModelId",
    "Parse",
    "Reason",
    "Revision",
    "RouterBinding",
    "RouterPolicy",
    "ScoreRow",
    "ScoringRecord",
    "SelectorRecord",
    "StrictModel",
    "UnknownLabel",
    "best_reason",
    "exact_reason",
    "field_rule",
    "strict_json",
]
