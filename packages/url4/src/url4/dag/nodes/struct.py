"""The inline ``{key: value, …}`` struct node (spec §5.3.11.3).

Split from :mod:`url4.dag.nodes.fetch` (module-size cap) by reason to change: this module
changes when the struct literal's decoding changes; ``fetch`` changes when the fetch
shapes change. ``url4.dag.nodes.fetch`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core._scan import skip_quoted, split_top_level
from url4.core.context import Context
from url4.core.errors import CollectionError

from url4.dag.node import DagNode, ExecutionContext, Payload  # isort: skip
from url4.dag.nodes._shared import _frame, _substitute  # isort: skip


@dataclass(eq=False)
class StructNode:
    """An inline ``{key: value, …}`` structured object (spec §5.3.11.3).

    The raw balanced-brace text is decoded at resolve time — after ``$``
    substitution of its string values — and re-emitted as canonical JSON, so a
    downstream ``$name.field`` path or RDS consumer sees a real object.
    """

    raw: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        return json.dumps(_decode_struct(self.raw, scope, ctx))


def _decode_struct(raw: str, scope: Context, ctx: ExecutionContext) -> dict:
    result: dict[str, object] = {}
    for fld in split_top_level(raw.strip()[1:-1], ","):
        key, sep, value = fld.partition(":")
        if not sep:
            raise CollectionError(f"malformed struct field {fld!r}")
        result[key.strip()] = _decode_struct_value(value.strip(), scope, ctx)
    return result


_NOT_SCALAR = object()


def _json_scalar(token: str) -> object:
    """A bare struct token's JSON scalar value (number/bool/null), or _NOT_SCALAR.

    Backs :class:`StructNode`'s "canonical JSON" guarantee (spec §5.3.11.3): a
    literal ``30`` becomes the number 30, ``true`` the boolean, ``null`` None.
    A bare word, a non-finite float, or anything else is not a scalar and stays
    a string.
    """
    try:
        parsed = json.loads(token)
    except (json.JSONDecodeError, ValueError):
        return _NOT_SCALAR
    # bool is an int subclass, so isinstance(_, int) covers true/false; a
    # non-finite float (NaN/Infinity) is not canonical JSON and stays a string.
    is_scalar = (
        parsed is None
        or isinstance(parsed, int)
        or (isinstance(parsed, float) and math.isfinite(parsed))
    )
    return parsed if is_scalar else _NOT_SCALAR


def _decode_struct_value(value: str, scope: Context, ctx: ExecutionContext) -> object:
    if value.startswith("{"):
        return _decode_struct(value, scope, ctx)
    quoted = False
    if value.startswith("'"):
        end = skip_quoted(value, 0)
        if end >= 2 and end == len(value):
            value = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
            quoted = True
    # WHY: a bare literal keeps its JSON scalar type (canonical JSON); a quoted value
    # is always a string, and a value carrying a $reference stays the substituted
    # string so a resolved id like "007" is never silently renumbered to 7.
    if not quoted and "$" not in value:
        scalar = _json_scalar(value)
        if scalar is not _NOT_SCALAR:
            return scalar
    return _substitute(value, scope, ctx)


__all__ = ["StructNode"]
