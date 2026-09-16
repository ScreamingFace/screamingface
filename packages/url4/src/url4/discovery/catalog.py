"""Linting a config catalog: is this document a well-formed `url4-config` schema?

`scope.py` answers "may this writer set this value". This answers the question underneath
it — "is the schema itself sound enough to judge anything against". A catalog with a leaf
that declares no `x-scope` is not a strict catalog that refuses writes; it is a catalog
with a HOLE, because `resolve_item` will not find that leaf at all and `enforce` will call
a legitimate value an unknown item.

WHY this exists at all: `x-scope` is not a JSON Schema keyword, and 2020-12 §6.5 requires
a validator to IGNORE keywords it does not recognise. So no validator, however strict,
will ever tell you that a leaf is missing its scope — every one of them is required to
say the document is fine. Enforcement and linting both have to be a parallel walk.

The rules are deliberately narrow. This does not re-implement JSON Schema validation; it
checks the properties a catalog needs in order to be USABLE as a permission model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from url4.discovery.scope import LADDER, X_SCOPE

CATALOG_ID = "url4-config"
"""Every config catalog declares this `$id`, and a manifest carries one at `config`.

It is a plain name rather than a URL because the catalog is EMBEDDED — the node rewrites
`$id` to an absolute URL when it composes the bundle (2020-12 §9.3), and an author who
had already picked a URL would have it silently replaced.
"""

UNSUPPORTED_KEYWORDS = frozenset(
    {
        "$ref",
        "$defs",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
    }
)
"""Keywords a catalog may not use, and the reason is composition, not taste.

A catalog is inlined into the node's bundle under `$defs/<mount>`. `$defs` of its own
would collide with the bundle's; `$ref` would resolve against the wrong base once
embedded. The applicator keywords (`oneOf`, `if`/`then`, ...) make "which subschema
applies" depend on the instance, so a scope walk could not name an item's scope without
first knowing its value — and `x-scope` has to be answerable from the schema ALONE, or
discovery cannot tell a caller what they may set before they set it.
"""

_STRUCTURAL_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "type",
        "properties",
        "additionalProperties",
        "propertyNames",
        "required",
        "default",
    }
)


class LintCode(StrEnum):
    """Catalog defects. Addressed to whoever AUTHORS a catalog, which is why they are a
    separate vocabulary from `scope.Code` — that one is addressed to a caller."""

    NOT_A_CATALOG = "catalog-wrong-id"
    UNSUPPORTED_KEYWORD = "catalog-unsupported-keyword"
    LEAF_WITHOUT_SCOPE = "catalog-leaf-without-scope"
    BAD_SCOPE = "catalog-bad-scope"
    LEAF_WITHOUT_TYPE = "catalog-leaf-without-type"
    LEAF_WITHOUT_DESCRIPTION = "catalog-leaf-without-description"
    OPEN_OBJECT = "catalog-open-object"
    WRITEONLY_WITH_DEFAULT = "catalog-writeonly-with-default"
    SYSTEM_NOT_PINNED = "catalog-system-not-pinned"
    DEFAULT_TYPE_MISMATCH = "catalog-default-type-mismatch"
    DEFAULT_NOT_IN_ENUM = "catalog-default-not-in-enum"
    EMPTY_GROUP = "catalog-empty-group"


@dataclass(frozen=True)
class Defect:
    """One catalog defect, located by dotted path so an author can go straight to it."""

    code: LintCode
    pointer: str
    detail: str

    def __str__(self) -> str:
        where = self.pointer or "<root>"
        return f"{where}: {self.detail} [{self.code}]"


class NotACatalog(ValueError):
    """The document is not a config catalog at all — linting it would be meaningless."""


def is_catalog(doc: Any) -> bool:
    """Does this document claim to BE a catalog?

    Checked before linting because the alternative is 46 spurious defects when someone
    points the linter at a manifest meta-schema: every one of its leaves lacks `x-scope`,
    correctly, because it is not that kind of document.
    """
    return isinstance(doc, Mapping) and doc.get("$id") == CATALOG_ID


def catalog_of(doc: Any) -> Mapping[str, Any] | None:
    """The catalog itself, or the one a manifest carries at `config`, or None."""
    if is_catalog(doc):
        return doc
    if isinstance(doc, Mapping):
        carried = doc.get("config")
        if is_catalog(carried):
            return carried
    return None


def is_group(schema: Mapping[str, Any]) -> bool:
    """A namespace: it has `properties` and does NOT carry `x-scope`.

    THE DISCRIMINATOR IS `x-scope`, NOT `properties`. An object that carries a scope is a
    LEAF whose value happens to be an object — `parameters.response_format` is one
    setting, not a namespace of sub-settings. Keying this on `properties` silently turned
    that item into a group and made its scope unenforceable.
    """
    return "properties" in schema and X_SCOPE not in schema


def is_leaf(schema: Mapping[str, Any]) -> bool:
    """A setting. Carries `x-scope`, whatever its type."""
    return X_SCOPE in schema


def lint_catalog(doc: Any) -> list[Defect]:
    """Every defect in one pass. Returns a list; never raises for a defect.

    Raises `NotACatalog` only when the document is the wrong KIND of thing, because that
    is a mistake by whoever invoked the linter rather than by the catalog's author.
    """
    catalog = catalog_of(doc)
    if catalog is None:
        found = doc.get("$id", "<none>") if isinstance(doc, Mapping) else type(doc).__name__
        raise NotACatalog(
            f"expected a config catalog (`$id: {CATALOG_ID!r}`) or a manifest carrying one "
            f"at `config`; found `$id: {found!r}`"
        )
    defects: list[Defect] = []
    _walk(catalog, "", defects, root=True)
    return defects


def _walk(schema: Any, path: str, defects: list[Defect], *, root: bool = False) -> None:
    if not isinstance(schema, Mapping):
        return
    defects.extend(_unsupported(schema, path))

    if is_leaf(schema):
        defects.extend(_check_leaf(schema, path))
        _walk_open_map(schema, path, defects)
        return

    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        defects.extend(_check_object(schema, path))
        if not properties and not root:
            defects.append(
                Defect(
                    LintCode.EMPTY_GROUP,
                    path,
                    "group declares no properties — it can hold nothing",
                )
            )
        for name, child in properties.items():
            child_path = f"{path}.{name}" if path else str(name)
            if isinstance(child, Mapping) and not is_leaf(child) and "properties" not in child:
                defects.append(
                    Defect(
                        LintCode.LEAF_WITHOUT_SCOPE,
                        child_path,
                        f"leaf declares no `{X_SCOPE}` — no validator will ever report this, "
                        "and `enforce` will call a legitimate value an unknown item",
                    )
                )
                defects.extend(_check_leaf_shape(child, child_path))
                continue
            _walk(child, child_path, defects)
    elif root:
        defects.append(Defect(LintCode.EMPTY_GROUP, path, "catalog declares no `properties`"))


def _walk_open_map(schema: Mapping[str, Any], path: str, defects: list[Defect]) -> None:
    """An OPEN MAP is `additionalProperties: <schema>` on a leaf: one setting whose KEYS
    the deployer chooses (a command table, a holdings shelf). Its value shape is linted,
    but the shape is not itself an item, so it needs no scope of its own."""
    shape = schema.get("additionalProperties")
    if isinstance(shape, Mapping):
        defects.extend(_unsupported(shape, f"{path}.<key>"))


def _unsupported(schema: Mapping[str, Any], path: str) -> list[Defect]:
    return [
        Defect(
            LintCode.UNSUPPORTED_KEYWORD,
            path,
            f"`{keyword}` is not usable in a catalog — it is inlined into the node's "
            "bundle, where a local $defs collides and a $ref resolves against the wrong base",
        )
        for keyword in sorted(UNSUPPORTED_KEYWORDS & set(schema))
    ]


def _check_object(schema: Mapping[str, Any], path: str) -> list[Defect]:
    """A group must be CLOSED. An open group silently accepts a typo'd item name, and a
    typo that is accepted is a setting that never takes effect."""
    if schema.get("additionalProperties") is not False:
        return [
            Defect(
                LintCode.OPEN_OBJECT,
                path,
                "object is not closed — add `additionalProperties: false`, or a typo'd "
                "item name is accepted and silently does nothing",
            )
        ]
    return []


def _check_leaf(item: Mapping[str, Any], path: str) -> list[Defect]:
    defects: list[Defect] = []
    scope = item.get(X_SCOPE)
    if scope not in LADDER:
        defects.append(
            Defect(LintCode.BAD_SCOPE, path, f"{X_SCOPE} {scope!r} is not one of {list(LADDER)}")
        )
    defects.extend(_check_leaf_shape(item, path))

    if item.get("writeOnly") and "default" in item:
        # A default on a secret is the secret, written into a document the node SERVES.
        defects.append(
            Defect(
                LintCode.WRITEONLY_WITH_DEFAULT,
                path,
                "writeOnly item carries a `default` — a catalog is served to callers, so "
                "that default is a published credential",
            )
        )
    if scope == "system" and not item.get("readOnly") and "default" not in item:
        # A system item nobody can set and nothing defaults to is unreachable: code cannot
        # be told to set it and no writer is allowed to.
        defects.append(
            Defect(
                LintCode.SYSTEM_NOT_PINNED,
                path,
                "system item is neither `readOnly` nor defaulted — nothing can ever give "
                "it a value",
            )
        )
    defects.extend(_check_default(item, path))
    return defects


def _check_leaf_shape(item: Mapping[str, Any], path: str) -> list[Defect]:
    """Every leaf needs a type and a description: the type is what `coerce` reads a header
    value with, and the description is the only thing a caller has to go on."""
    defects: list[Defect] = []
    if "type" not in item:
        defects.append(
            Defect(
                LintCode.LEAF_WITHOUT_TYPE,
                path,
                "leaf declares no `type` — a header carrier cannot type its value without one",
            )
        )
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        defects.append(
            Defect(
                LintCode.LEAF_WITHOUT_DESCRIPTION,
                path,
                "leaf declares no `description` — it is the only guidance a caller gets",
            )
        )
    return defects


def _check_default(item: Mapping[str, Any], path: str) -> list[Defect]:
    """A default that the item's own type or enum rejects is a value nothing can use."""
    if "default" not in item:
        return []
    from url4.discovery.scope import _type_ok, _typename  # noqa: PLC0415 - one owner of the rules

    value = item["default"]
    declared = item.get("type")
    defects: list[Defect] = []
    if declared is not None and not _type_ok(value, declared):
        defects.append(
            Defect(
                LintCode.DEFAULT_TYPE_MISMATCH,
                path,
                f"default is {_typename(value)} but the item declares {declared}",
            )
        )
    allowed = item.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        defects.append(
            Defect(LintCode.DEFAULT_NOT_IN_ENUM, path, f"default {value!r} is not in the enum")
        )
    return defects


def format_defects(defects: list[Defect]) -> str:
    """Render for a terminal. One per line, so `grep` works on the output."""
    return "\n".join(f"  - {defect}" for defect in defects)


__all__ = [
    "CATALOG_ID",
    "UNSUPPORTED_KEYWORDS",
    "Defect",
    "LintCode",
    "NotACatalog",
    "catalog_of",
    "format_defects",
    "is_catalog",
    "is_group",
    "is_leaf",
    "lint_catalog",
]
