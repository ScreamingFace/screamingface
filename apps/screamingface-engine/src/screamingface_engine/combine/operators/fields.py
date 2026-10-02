"""Field operators: pick a member by one JSON field, or build one object by field rules (E4a).

FEATURE: members that return JSON are joined by declared rules, not rewritten by a model.
STORY: as a researcher, Pick returns the chosen member's own JSON byte for byte, and Merge returns
one canonical JSON object that holds exactly the declared fields, each built by its own rule.

Mental model: a clerk with a form. Pick reads one box on every member's form and hands back the
whole form with the best box. Merge fills one new form box by box: each box has its own rule
(the common value, the biggest, one member's value, the union of lists, or a writer's text).

INVARIANT: each operator is pure and holds no mutable state. ``FieldReading`` values and results
are JSON values only (the original decoded value, never a ``Decimal``). A JSON ``null`` counts as
an absent field, like ``json_field@1``. A message names a rule or a field number, never a value.
WHY the v1 normalizers by function: ``field_rules@1`` and ``by_field@1`` call ``numeric`` and
``text`` of the v1 normalize module directly, so a later ``text@2`` needs ``field_rules@2``.
AIDEV-NOTE: the rule semantics (null is absent, the first holder wins a tie, union keeps the first
spelling) are v1 behavior pinned by the golden fixtures. A change is a new ``@version``.
AIDEV-NOTE: the comparison key conflates JSON types on purpose (v1): the text ``"true"`` and the
boolean ``true`` share a key, so do ``"[1,2]"`` and ``[1,2]``, and ``text`` casefolds a whole
object's canonical text, keys included. A JSON number is read as the number it is (max), never
through the 64-char / 2-digit-exponent limits of ``numeric@1``; only a string goes through them.
A field rule, projection or equals pick that finds no usable value raises ``NoVotes`` (reason
``no_votes``); the core turns it into an abstain (OME-1289 gap AB-D4). from_member null is a value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from screamingface_engine.combine.operators.normalize import numeric, text
from screamingface_engine.combine.ports import (
    FIELD_PATH,
    Answer,
    CombineInput,
    FieldReading,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SpecInvalid,
    canonical_json,
    loads_bounded,
)

_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_MEMBER = re.compile(r"member_[1-9][0-9]*")
_MAX_FIELDS = 64
_MAX_PATH_CHARS = 256
_WRITER_PREFIX = "writer_"
# WHY only this form: it is what numeric@1 writes (see reduce.py `_CANONICAL_NUMBER`).
_CANONICAL_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_NORMALIZE_CHOICES = (None, "text", "numeric")
_NORMALIZERS = MappingProxyType({"text": text, "numeric": numeric})
_RULE_KEYS = MappingProxyType(
    {
        "majority": frozenset({"field", "rule", "normalize"}),
        "max": frozenset({"field", "rule"}),
        "from_member": frozenset({"field", "rule", "member"}),
        "union": frozenset({"field", "rule", "normalize"}),
        "model": frozenset({"field", "rule"}),
    }
)
_RULES_INVALID = 'field_rules@1 takes {"fields": [...]} with one valid rule per field'
_Rule = Mapping[str, Any]
_Objects = tuple[tuple[str, dict[str, object]], ...]


# --- shared helpers ---------------------------------------------------------------------------


def _object(value: str | None, op_id: str) -> dict[str, object]:
    """The member's extracted value as a JSON object; anything else is a spec error."""
    try:
        decoded = None if value is None else loads_bounded(value)
        # WHY canonical_json here: a number like 1e999 decodes to inf, which json_object@1 never
        # lets through, but another extractor can. Every rule may then call canonical_json.
        canonical_json(decoded)
    except ValueError:
        decoded = None
    if not isinstance(decoded, dict):
        raise SpecInvalid(f"{op_id} needs JSON object values")
    return decoded


def _objects(combine_input: CombineInput, op_id: str) -> _Objects:
    """Every voter's JSON object, in author order."""
    return tuple(
        (answer.member_id, _object(answer.value, op_id)) for answer in combine_input.voters
    )


def _present(objects: _Objects, field: str) -> tuple[tuple[str, object], ...]:
    """The members whose object has ``field`` with a value that is not null."""
    return tuple((member, obj[field]) for member, obj in objects if obj.get(field) is not None)


def _text_of(value: object) -> str:
    return value if isinstance(value, str) else canonical_json(value)


def _key(value: object, normalize: str | None) -> str | None:
    """The comparison key of a field value: its text, normalized when asked; None if rejected."""
    if normalize is None:
        return _text_of(value)
    return _NORMALIZERS[normalize](_text_of(value), {}).value


def _no_usable(index: int) -> NoVotes:
    return NoVotes(f"field_rules@1 field {index} has no usable value", reason="no_votes")


# --- values@1 and project_field@1 -------------------------------------------------------------


def _check_values_args(args: OpArgs) -> None:
    field = args.get("field")
    if (
        set(args) != {"field"}
        or not isinstance(field, str)
        or FIELD_PATH.fullmatch(field) is None
        or len(field) > _MAX_PATH_CHARS
    ):
        raise SpecInvalid('values@1 takes exactly {"field": <field path>}')


def values(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Each voter's value of the compared field, for the evidence."""
    held = MappingProxyType({answer.member_id: answer.value for answer in combine_input.voters})
    return Reduction(fields=(FieldReading(str(args["field"]), "values", held, None),))


def _check_project_args(args: OpArgs) -> None:
    field = args.get("field")
    if set(args) != {"field"} or not isinstance(field, str) or _FIELD.fullmatch(field) is None:
        raise SpecInvalid('project_field@1 takes exactly {"field": <field name>}')


def project_field(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The JSON object ``{member: value}`` of one field: all a writer model may see."""
    field = str(args["field"])
    present = dict(_present(_objects(combine_input, "project_field@1"), field))
    if not present:
        raise NoVotes("project_field@1: no member has the field", reason="no_votes")
    reading = FieldReading(field, "project", MappingProxyType(present), None)
    return Reduction(text=canonical_json(present), fields=(reading,))


# --- by_field@1 -------------------------------------------------------------------------------


def _check_by_field_args(args: OpArgs) -> None:
    order = args.get("order")
    if order in ("max", "min") and set(args) == {"order"}:
        return
    if (
        order == "equals"
        and set(args) == {"order", "value", "normalize"}
        and isinstance(args["value"], str)
        and args["normalize"] in _NORMALIZE_CHOICES
    ):
        return
    raise SpecInvalid(
        'by_field@1 takes {"order": "max" | "min"} or '
        '{"order": "equals", "value": <text>, "normalize": null | "text" | "numeric"}'
    )


def _by_extreme(voters: Sequence[Answer], order: object) -> Selection:
    numbers: list[tuple[str, Decimal]] = []
    for answer in voters:
        if answer.value is None or _CANONICAL_NUMBER.fullmatch(answer.value) is None:
            raise SpecInvalid("by_field@1 max and min need numeric values")
        numbers.append((answer.member_id, Decimal(answer.value)))
    scores = [number for _, number in numbers]
    best = max(scores) if order == "max" else min(scores)
    holders = [member for member, number in numbers if number == best]
    return Selection(chosen=(holders[0],), tie=len(holders) > 1)


def _target(args: OpArgs) -> str:
    """The value to match: as written, or in the declared normalizer's form."""
    value, normalize = str(args["value"]), args["normalize"]
    if not isinstance(normalize, str):
        return value
    target = _NORMALIZERS[normalize](value, {}).value
    if target is None:
        raise SpecInvalid("by_field@1 equals value does not normalize")
    return target


def _by_equals(voters: Sequence[Answer], args: OpArgs) -> Selection:
    target = _target(args)
    holders = [answer.member_id for answer in voters if answer.value == target]
    if not holders:
        raise NoVotes("no member value equals the by_field@1 target", reason="no_votes")
    return Selection(chosen=(holders[0],), tie=len(holders) > 1)


def by_field(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The member whose field is the largest, the smallest, or equal to the target.

    The first member in author order wins a tie; ``agreement`` is always None.

    INVARIANT: the voters' values are already normalized by the spec's normalize step, so that step
    must be ``<normalize>@1`` matching the ``normalize`` arg (the SDK pairs them). The target is
    normalized here once; a voter value is never normalized again (``text@1`` is not idempotent).
    """
    if args["order"] == "equals":
        return _by_equals(combine_input.voters, args)
    return _by_extreme(combine_input.voters, args["order"])


# --- field_rules@1 ----------------------------------------------------------------------------


def _majority(
    rule: _Rule, combine_input: CombineInput, held: Mapping[str, object], index: int
) -> object:
    """The value of the largest group of equal keys; the first group wins a tie."""
    counts: dict[str, int] = {}
    firsts: dict[str, object] = {}
    for value in held.values():
        key = _key(value, rule["normalize"])
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
            firsts.setdefault(key, value)
    if not counts:
        raise _no_usable(index)
    return firsts[max(counts, key=lambda key: counts[key])]


def _number(value: object) -> Decimal | None:
    """A JSON number as it is (finite: see ``_object``); a string through ``numeric@1``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(repr(value))
    parsed = numeric(value, {}).value if isinstance(value, str) else None
    return None if parsed is None else Decimal(parsed)


def _maximum(
    rule: _Rule, combine_input: CombineInput, held: Mapping[str, object], index: int
) -> object:
    """The original value of the first holder of the largest number; non-numbers are skipped."""
    best: Decimal | None = None
    result: object = None
    for value in held.values():
        number = _number(value)
        if number is not None and (best is None or number > best):
            best, result = number, value
    if best is None:
        raise _no_usable(index)
    return result


def _from_member(
    rule: _Rule, combine_input: CombineInput, held: Mapping[str, object], index: int
) -> object:
    """That member's value; null when it is not a voter or lacks the field."""
    member = rule["member"]
    if member not in combine_input.members:
        raise SpecInvalid("field_rules@1 from_member names a member the spec does not have")
    return held.get(member)


def _union(
    rule: _Rule, combine_input: CombineInput, held: Mapping[str, object], index: int
) -> object:
    """The items of every list value, each key once, as the first spelling, in author order."""
    lists = [value for value in held.values() if isinstance(value, list)]
    if not lists:
        raise _no_usable(index)
    seen: set[str] = set()  # membership only; the order comes from the lists
    merged: list[object] = []
    for item in (item for items in lists for item in items):
        key = _key(item, rule["normalize"])
        if key is not None and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _model(
    rule: _Rule, combine_input: CombineInput, held: Mapping[str, object], index: int
) -> object:
    """The writer model's text for this field, as it is."""
    writer = combine_input.signals.get(_WRITER_PREFIX + str(rule["field"]))
    if writer is None:
        raise SpecInvalid("field_rules@1 needs a writer signal for each model field")
    return writer


_RULES = MappingProxyType(
    {
        "majority": _majority,
        "max": _maximum,
        "from_member": _from_member,
        "union": _union,
        "model": _model,
    }
)


def _member_ok(rule: Mapping[str, object]) -> bool:
    if rule["rule"] != "from_member":
        return True
    member = rule["member"]
    return isinstance(member, str) and _MEMBER.fullmatch(member) is not None


def _valid_rule(rule: object) -> bool:
    if not isinstance(rule, dict):
        return False
    kind, field = rule.get("rule"), rule.get("field")
    return (
        isinstance(kind, str)
        and kind in _RULE_KEYS
        and set(rule) == _RULE_KEYS[kind]
        and isinstance(field, str)
        and _FIELD.fullmatch(field) is not None
        and rule.get("normalize") in _NORMALIZE_CHOICES
        and _member_ok(rule)
    )


def _check_field_rules_args(args: OpArgs) -> None:
    rules = args.get("fields")
    if set(args) != {"fields"} or not isinstance(rules, list):
        raise SpecInvalid(_RULES_INVALID)
    if not 1 <= len(rules) <= _MAX_FIELDS or not all(_valid_rule(rule) for rule in rules):
        raise SpecInvalid(_RULES_INVALID)
    if len({rule["field"] for rule in rules}) != len(rules):
        raise SpecInvalid(_RULES_INVALID)


def field_rules(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """One object with exactly the declared fields, each by its own rule, in canonical JSON."""
    objects = _objects(combine_input, "field_rules@1")
    readings: list[FieldReading] = []
    for index, rule in enumerate(args["fields"], start=1):  # type: ignore[arg-type]
        held = dict(_present(objects, rule["field"]))
        result = _RULES[rule["rule"]](rule, combine_input, held, index)
        readings.append(FieldReading(rule["field"], rule["rule"], MappingProxyType(held), result))
    built = {reading.field: reading.result for reading in readings}
    return Reduction(fields=tuple(readings), text=canonical_json(built))


# --- built@1 ----------------------------------------------------------------------------------


def built(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The text the reduce step built is the answer; no member is chosen."""
    if reduction.text is None:
        raise SpecInvalid("built@1 needs a built text")
    return Selection(chosen=(), output=reduction.text)


# AIDEV-NOTE: the top level of an args schema is read-only; the nested "properties" stays a plain
# dict because ports.catalog_entry deep-copies the schema and a mappingproxy cannot be deep-copied.
OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor(
        "values",
        1,
        "reduce",
        "Each voter's value of one compared field, for the evidence.",
        values,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"field": {"type": "string"}},
                "required": ("field",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_values_args,
    ),
    OperatorDescriptor(
        "by_field",
        1,
        "select",
        "The member whose field is the largest, the smallest or equal to a value.",
        by_field,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {
                    "order": {"enum": ("max", "min", "equals")},
                    "value": {"type": "string"},
                    "normalize": {"enum": _NORMALIZE_CHOICES},
                },
                "required": ("order",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_by_field_args,
    ),
    OperatorDescriptor(
        "field_rules",
        1,
        "reduce",
        "One JSON object built field by field: majority, max, from_member, union or model.",
        field_rules,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": _MAX_FIELDS,
                        "items": {"type": "object"},
                    }
                },
                "required": ("fields",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_field_rules_args,
    ),
    OperatorDescriptor(
        "project_field",
        1,
        "reduce",
        "The values of one field, by member, as one JSON object.",
        project_field,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"field": {"type": "string"}},
                "required": ("field",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_project_args,
    ),
    OperatorDescriptor("built", 1, "select", "The built text is the answer.", built),
)

__all__ = ["OPERATORS"]
