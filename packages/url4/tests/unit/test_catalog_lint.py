"""Linting a config catalog (url4.discovery.catalog).

STORY: as a catalog author I get told what is wrong with my schema BEFORE it is served,
because no JSON Schema validator will ever tell me — 2020-12 §6.5 requires a validator to
ignore `x-scope`, so every one of them calls a catalog with a scopeless leaf valid.

The corpus here is SELF-CONTAINED on purpose. An earlier version of this walker kept its
fixtures in a scratch directory next to the repo; the directory was deleted and the whole
suite went with it. `GOOD` is a minimal but complete catalog, and every negative case
MUTATES it — so a rule cannot pass vacuously against a fixture that never exercised it.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from url4.discovery.catalog import (
    CATALOG_ID,
    UNSUPPORTED_KEYWORDS,
    LintCode,
    NotACatalog,
    format_defects,
    is_catalog,
    is_group,
    is_leaf,
    lint_catalog,
)

GOOD: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CATALOG_ID,
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "models": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {
                    "type": "string",
                    "x-scope": "user",
                    "description": "Model id the expression addresses.",
                    "enum": ["a", "b"],
                    "default": "a",
                }
            },
        },
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "temperature": {
                    "type": "number",
                    "x-scope": "user",
                    "description": "Sampling temperature.",
                    "default": 1.0,
                },
                # A STRUCTURED LEAF: it has `properties` AND `x-scope`, so it is one
                # setting whose value is an object — not a namespace of sub-items.
                "response_format": {
                    "type": "object",
                    "x-scope": "user",
                    "description": "Response format object passed through verbatim.",
                    "properties": {"type": {"type": "string"}},
                },
            },
        },
        "credentials": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "api_key": {
                    "type": "string",
                    "x-scope": "node",
                    "writeOnly": True,
                    "description": "Upstream API key; a node file names a declared secret.",
                }
            },
        },
        "endpoint": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "build_id": {
                    "type": "string",
                    "x-scope": "system",
                    "readOnly": True,
                    "description": "Commit the endpoint was built from.",
                }
            },
        },
        # An OPEN MAP: one setting whose KEYS the deployer chooses.
        "commands": {
            "type": "object",
            "x-scope": "node",
            "description": "Route path to argv template.",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
            "default": {},
        },
    },
}


def mutate(**path_value: Any) -> dict[str, Any]:
    """A copy of GOOD with one dotted path replaced (or deleted with `...`)."""
    doc = copy.deepcopy(GOOD)
    for dotted, value in path_value.items():
        parts = dotted.replace("__", ".").split(".")
        node = doc
        for part in parts[:-1]:
            node = node["properties"][part] if part in node.get("properties", {}) else node[part]
        if value is ...:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return doc


def codes(doc: Any) -> set[LintCode]:
    return {d.code for d in lint_catalog(doc)}


# --- the good catalog -------------------------------------------------------------


def test_the_reference_catalog_is_clean() -> None:
    """If this ever fails, every negative case below is testing the wrong baseline."""
    assert lint_catalog(GOOD) == []


def test_a_manifest_carrying_a_catalog_is_linted_through_it() -> None:
    assert lint_catalog({"$id": "some-manifest", "config": GOOD}) == []


# --- is this even a catalog? ------------------------------------------------------


def test_the_wrong_id_is_not_a_catalog() -> None:
    # Pointed at a manifest meta-schema, the linter once emitted 46 defects — every leaf
    # "missing x-scope", correctly, because it is not that kind of document.
    assert not is_catalog({"$id": "https://url4.ai/schemas/url4-endpoint-manifest/1"})
    with pytest.raises(NotACatalog, match="expected a config catalog"):
        lint_catalog({"$id": "https://url4.ai/schemas/url4-endpoint-manifest/1"})


def test_a_non_object_is_not_a_catalog() -> None:
    with pytest.raises(NotACatalog):
        lint_catalog(["nope"])


# --- the group / leaf discriminator ------------------------------------------------


def test_x_scope_is_the_discriminator_not_properties() -> None:
    """THE BUG THIS ENCODES. `response_format` has `properties` AND `x-scope`. Keying
    "is it a group" on `properties` turned that item into a namespace and made its scope
    unenforceable. It is the only occurrence in the whole real corpus, so a fixture that
    omits it passes a broken implementation."""
    structured = GOOD["properties"]["parameters"]["properties"]["response_format"]
    assert is_leaf(structured)
    assert not is_group(structured)

    namespace = GOOD["properties"]["parameters"]
    assert is_group(namespace)
    assert not is_leaf(namespace)


def test_a_structured_leafs_interior_needs_no_scope_of_its_own() -> None:
    """Its `properties` describe the VALUE, not more items — so they are not leaves and
    must not be reported as scopeless ones."""
    assert lint_catalog(GOOD) == []


# --- leaf rules --------------------------------------------------------------------


def test_a_leaf_without_a_scope_is_reported() -> None:
    doc = copy.deepcopy(GOOD)
    del doc["properties"]["models"]["properties"]["name"]["x-scope"]
    assert LintCode.LEAF_WITHOUT_SCOPE in codes(doc)


@pytest.mark.parametrize("scope", ["User", "admin", "", None, 1])
def test_a_scope_outside_the_ladder_is_reported(scope: Any) -> None:
    doc = copy.deepcopy(GOOD)
    doc["properties"]["models"]["properties"]["name"]["x-scope"] = scope
    assert LintCode.BAD_SCOPE in codes(doc)


def test_a_leaf_without_a_type_is_reported() -> None:
    doc = copy.deepcopy(GOOD)
    del doc["properties"]["parameters"]["properties"]["temperature"]["type"]
    assert LintCode.LEAF_WITHOUT_TYPE in codes(doc)


@pytest.mark.parametrize("description", [None, "", "   "])
def test_a_leaf_without_a_usable_description_is_reported(description: Any) -> None:
    doc = copy.deepcopy(GOOD)
    item = doc["properties"]["models"]["properties"]["name"]
    if description is None:
        del item["description"]
    else:
        item["description"] = description
    assert LintCode.LEAF_WITHOUT_DESCRIPTION in codes(doc)


# --- closure -----------------------------------------------------------------------


def test_an_open_group_is_reported() -> None:
    """A typo'd item name in an open group is ACCEPTED, and an accepted typo is a setting
    that silently never takes effect."""
    doc = copy.deepcopy(GOOD)
    del doc["properties"]["models"]["additionalProperties"]
    assert LintCode.OPEN_OBJECT in codes(doc)


def test_an_open_map_leaf_is_not_an_open_group() -> None:
    """`commands` has `additionalProperties: <schema>` — deployer-chosen KEYS, which is a
    legitimate shape and must not be confused with a group that forgot to close."""
    assert LintCode.OPEN_OBJECT not in codes(GOOD)


# --- secrets -----------------------------------------------------------------------


def test_a_writeonly_item_with_a_default_is_reported() -> None:
    """The catalog is SERVED to callers, so that default is a published credential."""
    doc = copy.deepcopy(GOOD)
    doc["properties"]["credentials"]["properties"]["api_key"]["default"] = "sk-live-oops"
    assert LintCode.WRITEONLY_WITH_DEFAULT in codes(doc)


def test_a_writeonly_item_without_a_default_is_fine() -> None:
    """The asymmetry is deliberate: a drift check that expects every item to carry the
    code's default must exempt writeOnly, or it reports the SAFE case as a defect."""
    assert lint_catalog(GOOD) == []


# --- system items ------------------------------------------------------------------


def test_a_system_item_that_is_neither_readonly_nor_defaulted_is_reported() -> None:
    """Nothing could ever give it a value: no writer is allowed to, and there is no
    default to fall back on."""
    doc = copy.deepcopy(GOOD)
    del doc["properties"]["endpoint"]["properties"]["build_id"]["readOnly"]
    assert LintCode.SYSTEM_NOT_PINNED in codes(doc)


def test_a_defaulted_system_item_is_fine() -> None:
    doc = copy.deepcopy(GOOD)
    item = doc["properties"]["endpoint"]["properties"]["build_id"]
    del item["readOnly"]
    item["default"] = "unknown"
    assert LintCode.SYSTEM_NOT_PINNED not in codes(doc)


# --- defaults ----------------------------------------------------------------------


def test_a_default_of_the_wrong_type_is_reported() -> None:
    doc = copy.deepcopy(GOOD)
    doc["properties"]["parameters"]["properties"]["temperature"]["default"] = "warm"
    assert LintCode.DEFAULT_TYPE_MISMATCH in codes(doc)


def test_a_default_outside_its_own_enum_is_reported() -> None:
    doc = copy.deepcopy(GOOD)
    doc["properties"]["models"]["properties"]["name"]["default"] = "zzz"
    assert LintCode.DEFAULT_NOT_IN_ENUM in codes(doc)


# --- composition keywords ----------------------------------------------------------


@pytest.mark.parametrize("keyword", sorted(UNSUPPORTED_KEYWORDS))
def test_every_unsupported_keyword_is_rejected(keyword: str) -> None:
    """A catalog is INLINED into the node's bundle. A local `$defs` collides with the
    bundle's, a `$ref` resolves against the wrong base, and an applicator makes an item's
    scope depend on the instance — which discovery must answer without one."""
    doc = copy.deepcopy(GOOD)
    doc["properties"]["models"]["properties"]["name"][keyword] = {}
    assert LintCode.UNSUPPORTED_KEYWORD in codes(doc)


def test_an_unsupported_keyword_at_the_root_is_rejected() -> None:
    doc = copy.deepcopy(GOOD)
    doc["$defs"] = {"shared": {"type": "string"}}
    assert LintCode.UNSUPPORTED_KEYWORD in codes(doc)


# --- the checks are non-vacuous ----------------------------------------------------


def _mutations() -> list[dict[str, Any]]:
    """One mutation per rule, so every LintCode has something that produces it."""
    out: list[dict[str, Any]] = []

    def drop(*path: str) -> None:
        doc = copy.deepcopy(GOOD)
        node: Any = doc
        for part in path[:-1]:
            node = node["properties"][part] if part in node.get("properties", {}) else node[part]
        node.pop(path[-1], None)
        out.append(doc)

    def put(*path: str, value: Any) -> None:
        doc = copy.deepcopy(GOOD)
        node: Any = doc
        for part in path[:-1]:
            node = node["properties"][part] if part in node.get("properties", {}) else node[part]
        node[path[-1]] = value
        out.append(doc)

    drop("models", "name", "x-scope")
    put("models", "name", "x-scope", value="nope")
    drop("parameters", "temperature", "type")
    drop("models", "name", "description")
    drop("models", "additionalProperties")
    put("credentials", "api_key", "default", value="sk-x")
    drop("endpoint", "build_id", "readOnly")
    put("parameters", "temperature", "default", value="warm")
    put("models", "name", "default", value="zzz")
    put("$defs", value={})
    put("models", "properties", value={})
    return out


def test_every_lint_code_is_reachable() -> None:
    """A code no mutation produces is either dead or an untested rule. Both are worth
    knowing about, and neither shows up as a failing test on its own."""
    produced: set[LintCode] = set()
    for doc in _mutations():
        produced |= codes(doc)

    unreachable = set(LintCode) - produced - {LintCode.NOT_A_CATALOG}
    assert unreachable == set(), f"no mutation produces {sorted(unreachable)}"


def test_defects_render_one_per_line_for_grep() -> None:
    doc = copy.deepcopy(GOOD)
    del doc["properties"]["models"]["properties"]["name"]["description"]
    rendered = format_defects(lint_catalog(doc))
    assert rendered.count("\n") == len(lint_catalog(doc)) - 1
    assert "models.name" in rendered
