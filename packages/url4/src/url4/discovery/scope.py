"""`x-scope` enforcement at request time: may THIS writer set THIS item, to THIS value?

`x-scope` is not a JSON Schema keyword. A validator is REQUIRED to ignore keywords it does
not know, so no amount of schema validation enforces scope — it takes a parallel walk over
the same document, which is what this module is.

The ladder is ``system < node < user`` and an item names the MOST PERMISSIVE level allowed
to set it — a floor, not a ceiling. `x-scope: node` means a deployer may set it and a
caller may not; `x-scope: user` means a caller may. So a request-time writer may set
exactly the `user` items, and everything else is refused rather than ignored.

Refused, never ignored: a caller who sends `credentials.api_key` and gets a `200` has been
told their key was accepted. Every violation is reported, and all of them at once — a
config with four mistakes should take one round trip, not four.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

SYSTEM = "system"
NODE = "node"
USER = "user"

LADDER: tuple[str, ...] = (SYSTEM, NODE, USER)
"""Least to most permissive. An item's `x-scope` is the most permissive setter allowed."""

X_SCOPE = "x-scope"


class Code(StrEnum):
    """Wire-visible violation codes. They appear in the RFC 9457 problem, so they are
    part of the contract: renaming one is a breaking change for any client that branches
    on it."""

    UNKNOWN_ITEM = "config-unknown-item"
    SCOPE_VIOLATION = "config-scope-violation"
    TYPE_MISMATCH = "config-type-mismatch"
    OUT_OF_ENUM = "config-out-of-enum"
    NOT_SETTABLE = "config-not-settable"


@dataclass(frozen=True)
class Violation:
    """One refusal, naming the item so a client can fix exactly that field."""

    code: Code
    pointer: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": str(self.code), "pointer": self.pointer, "detail": self.detail}


def settable_by(actor: str, item_scope: str) -> bool:
    """May ``actor`` set an item whose floor is ``item_scope``?

    An actor may set an item at or below its own level on the ladder. A caller (`user`)
    may set `user` items; a `node` item's floor is below them, so it is the deployer's.
    """
    if actor not in LADDER or item_scope not in LADDER:
        return False
    return item_scope == actor


def enforce(
    values: Mapping[str, Any], schema: Mapping[str, Any], *, actor: str = USER
) -> list[Violation]:
    """Check a flat ``{dotted.path: value}`` map against the schema the endpoint served.

    Returns every violation rather than raising on the first, so one response can fix a
    whole request. An empty list means the values may be forwarded as-is.
    """
    violations: list[Violation] = []
    for path, value in values.items():
        item = resolve_item(schema, path)
        if item is None:
            violations.append(
                Violation(Code.UNKNOWN_ITEM, path, f"no item {path!r} in this schema")
            )
            continue
        violations.extend(_check_item(path, value, item, actor))
    return violations


def resolve_item(schema: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    """Walk a dotted path to its leaf, or None.

    An object carrying `x-scope` is a LEAF (a structured setting whose value happens to be
    an object); one without is a namespace. So descent stops at the first `x-scope`, and a
    path that tries to reach inside a structured leaf does not resolve — its interior is
    the value, not more items.
    """
    segments = path.split(".")
    current: Any = schema
    for index, segment in enumerate(segments):
        properties = current.get("properties") if isinstance(current, Mapping) else None
        if not isinstance(properties, Mapping) or segment not in properties:
            current = None
            break
        current = properties[segment]
        if isinstance(current, Mapping) and X_SCOPE in current:
            # A leaf. Any remaining segment addresses INSIDE its value, not a sub-item,
            # so a path that keeps going has not found an item.
            if index != len(segments) - 1:
                current = None
            break
    return current if isinstance(current, Mapping) and X_SCOPE in current else None


def _check_item(path: str, value: Any, item: Mapping[str, Any], actor: str) -> list[Violation]:
    refusal = _refusal(path, item, actor)
    declared = item.get("type")
    allowed = item.get("enum")

    if refusal is None and declared is not None and not _type_ok(value, declared):
        # Checked before the enum: an enum message about a value of the wrong type only
        # adds noise to something the caller already has to fix.
        refusal = Violation(
            Code.TYPE_MISMATCH, path, f"expected {declared}, got {_typename(value)}"
        )
    elif refusal is None and isinstance(allowed, list) and value not in allowed:
        refusal = Violation(Code.OUT_OF_ENUM, path, f"{value!r} is not one of {allowed}")
    return [] if refusal is None else [refusal]


def _refusal(path: str, item: Mapping[str, Any], actor: str) -> Violation | None:
    """Why this writer may not set this item at all, or None if they may.

    `readOnly`/`writeOnly` are checked BEFORE scope so the message names the real reason.
    A `writeOnly` item is a secret the node resolves from its own store; a caller
    supplying one is attempting to inject a credential, not misreading the ladder.
    """
    scope = item.get(X_SCOPE)
    if not isinstance(scope, str):  # pragma: no cover - catalog lint rejects this
        scope = ""
    # First match wins, and the ORDER is the point: a caller sending a writeOnly item gets
    # told it is a secret, not that they picked the wrong scope.
    reasons = (
        (not scope, Code.UNKNOWN_ITEM, f"item {path!r} declares no {X_SCOPE}"),
        (bool(item.get("readOnly")), Code.NOT_SETTABLE, f"{path!r} is readOnly"),
        (
            bool(item.get("writeOnly")),
            Code.NOT_SETTABLE,
            f"{path!r} is writeOnly — resolved from a declared secret, never sent by a caller",
        ),
        (
            bool(scope) and not settable_by(actor, scope),
            Code.SCOPE_VIOLATION,
            f"{path!r} is {scope}-scope; a {actor} may not set it",
        ),
    )
    return next((Violation(code, path, detail) for hit, code, detail in reasons if hit), None)


# `bool` is tested before `int` because it subclasses it — otherwise `true` would satisfy
# `"type": "integer"`. Each entry is a predicate rather than a type so that distinction,
# and `null`, are expressible in one table.
_TYPE_CHECKS: dict[str, Any] = {
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "object": lambda v: isinstance(v, Mapping),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _type_ok(value: Any, declared: Any) -> bool:
    if isinstance(declared, list):
        return any(_type_ok(value, one) for one in declared)
    check = _TYPE_CHECKS.get(str(declared))
    return check is not None and check(value)


def _typename(value: Any) -> str:
    """The JSON name for a value's type, so a message speaks the wire's language."""
    for name in ("null", "boolean", "string", "integer", "number", "object", "array"):
        if _TYPE_CHECKS[name](value):
            return name
    return type(value).__name__


# --- nested instances -------------------------------------------------------------
#
# `enforce` takes the FLAT map a request carrier produces. A node file (`url4.json`, or a
# mount's `config` block) is the same information NESTED, so it needs a walk rather than a
# lookup — but the per-item rules must not be a second copy, or the two would drift and a
# value legal at rest would be refused in flight. Both funnel into `_check_item`.

SECRET_KEY = "$secret"
"""A `writeOnly` item in a node file is never a literal — it names a declared secret."""


def is_secret_ref(value: Any) -> bool:
    """Does this value CLAIM to be a secret reference?

    Claim, not "is valid": `{"$secret": 123}` is reported as a malformed reference rather
    than falling through to the type check and being reported as the wrong type, which
    would send an author looking in the wrong place.
    """
    return isinstance(value, Mapping) and SECRET_KEY in value


def walk_config(
    instance: Any,
    catalog: Mapping[str, Any],
    *,
    actor: str = NODE,
    secrets: Any = None,
    path: str = "",
) -> list[Violation]:
    """Check a NESTED config object against a catalog, for one writer.

    ``actor`` is who is writing: `NODE` for a node file or a mount's `config`, `USER` for
    request-time values that arrived nested rather than flat.

    ``secrets`` is the set of secret names the manifest declares; pass ``None`` to skip
    declaration checking. Passing an empty set instead would report every reference as
    undeclared, which is not the same statement.
    """
    violations: list[Violation] = []
    _walk_instance(instance, catalog, path, actor, secrets, violations)
    return violations


def _walk_instance(
    instance: Any,
    schema: Any,
    path: str,
    actor: str,
    secrets: Any,
    out: list[Violation],
) -> None:
    if not isinstance(instance, Mapping) or not isinstance(schema, Mapping):
        return
    properties = schema.get("properties")
    open_map = schema.get("additionalProperties")

    for key, value in instance.items():
        here = f"{path}.{key}" if path else str(key)
        child = properties.get(key) if isinstance(properties, Mapping) else None

        if child is None and isinstance(open_map, Mapping):
            # An OPEN MAP: the deployer chose this key. The parent leaf already carried
            # the scope, so what is checked here is only the value's SHAPE.
            out.extend(_check_shape(here, value, open_map))
            continue
        if not isinstance(child, Mapping):
            out.append(Violation(Code.UNKNOWN_ITEM, here, f"no item {here!r} in the catalog"))
            continue
        if X_SCOPE in child:
            out.extend(_check_written(here, value, child, actor, secrets))
            continue
        _walk_instance(value, child, here, actor, secrets, out)


def _check_written(
    path: str, value: Any, item: Mapping[str, Any], actor: str, secrets: Any
) -> list[Violation]:
    """One written leaf: a secret reference, an open map, or a plain literal."""
    if item.get("writeOnly") or is_secret_ref(value):
        return _check_secret_ref(path, value, item, secrets)

    violations = _check_item(path, value, item, actor)
    shape = item.get("additionalProperties")
    if violations or not isinstance(shape, Mapping) or not isinstance(value, Mapping):
        return violations

    # An OPEN MAP: the leaf's own scope is settled, but each deployer-chosen key holds a
    # VALUE whose shape the catalog also declares. Without descending, a shell string
    # where the shape says array passes — and the node then execs one argv token holding
    # a whole command line.
    for key, entry in value.items():
        violations.extend(_check_shape(f"{path}.{key}", entry, shape))
    return violations


def _check_secret_ref(
    path: str, value: Any, item: Mapping[str, Any], secrets: Any
) -> list[Violation]:
    """A writeOnly item carries `{"$secret": "<name>"}` and nothing else.

    A literal here is the failure this rule exists for: a key pasted into a node file is a
    key in version control.
    """
    name = value.get(SECRET_KEY) if isinstance(value, Mapping) else None
    extra = sorted(set(value) - {SECRET_KEY}) if isinstance(value, Mapping) else []
    malformed = not isinstance(name, str) or not name or bool(extra)

    # First match wins. The ORDER is the point: a literal in a writeOnly slot is the
    # failure this rule exists for — a key pasted into a node file is a key in version
    # control — so it is named before anything subtler about the reference's shape.
    reasons = (
        (
            not is_secret_ref(value),
            Code.NOT_SETTABLE,
            f"{path!r} is writeOnly — write {{{SECRET_KEY!r}: <name>}}, never a literal",
        ),
        (
            not item.get("writeOnly"),
            Code.TYPE_MISMATCH,
            f"{path!r} is not writeOnly, so a {SECRET_KEY} reference is not meaningful",
        ),
        (
            malformed,
            Code.TYPE_MISMATCH,
            f"malformed secret reference: expected exactly {{{SECRET_KEY!r}: <name>}}",
        ),
        (
            secrets is not None and name not in secrets,
            Code.UNKNOWN_ITEM,
            f"secret {name!r} is not declared by the manifest",
        ),
    )
    hit = next(((code, detail) for ok, code, detail in reasons if ok), None)
    return [] if hit is None else [Violation(hit[0], path, hit[1])]


def _check_shape(path: str, value: Any, shape: Mapping[str, Any]) -> list[Violation]:
    """The value shape inside an open map — a command's argv, a provider's table.

    Without this an operator could write a shell STRING where the shape says array, or an
    unknown key inside the value, and the walk would pass it because the parent leaf's
    own scope was fine.
    """
    declared = shape.get("type")
    if declared is not None and not _type_ok(value, declared):
        return [Violation(Code.TYPE_MISMATCH, path, f"expected {declared}, got {_typename(value)}")]
    properties = shape.get("properties")
    if not isinstance(value, Mapping) or not isinstance(properties, Mapping):
        return []
    out: list[Violation] = []
    if shape.get("additionalProperties") is False:
        unknown = sorted(set(map(str, value)) - set(map(str, properties)))
        out += [
            Violation(Code.UNKNOWN_ITEM, f"{path}.{k}", f"no key {k!r} in this value shape")
            for k in unknown
        ]
    for key, sub in properties.items():
        if key in value and isinstance(sub, Mapping):
            out.extend(_check_shape(f"{path}.{key}", value[key], sub))
    return out


__all__ = [
    "LADDER",
    "NODE",
    "SECRET_KEY",
    "SYSTEM",
    "USER",
    "X_SCOPE",
    "Code",
    "Violation",
    "enforce",
    "is_secret_ref",
    "resolve_item",
    "settable_by",
    "walk_config",
]
