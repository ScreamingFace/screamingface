"""Walking a NESTED config instance against a catalog (url4.discovery.scope.walk_config).

STORY: as a node operator I write `url4.json` — or a mount's `config` block — and the node
tells me, before it binds, that I set something that is not mine to set, pasted a literal
where a secret reference belongs, or named an item that does not exist.

`enforce` handles the FLAT map a request carrier produces. This handles the same
information nested. Both funnel into the same per-item rules, so a value legal at rest
cannot be refused in flight.
"""

from __future__ import annotations

from typing import Any

import pytest

from url4.discovery.scope import USER, Code, is_secret_ref, walk_config

CATALOG: dict[str, Any] = {
    "$id": "url4-config",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "server": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "host": {"type": "string", "x-scope": "node", "description": "Bind address."},
                "port": {"type": "integer", "x-scope": "node", "description": "Bind port."},
            },
        },
        "models": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {
                    "type": "string",
                    "x-scope": "user",
                    "description": "Model id.",
                    "enum": ["a", "b"],
                }
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
                    "description": "Upstream key.",
                }
            },
        },
        "commands": {
            "type": "object",
            "x-scope": "node",
            "description": "Route path to argv.",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "reads": {
            "type": "object",
            "x-scope": "node",
            "description": "Path to provider.",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "value": {"type": "string"},
                    "file": {"type": "string"},
                    "media_type": {"type": "string"},
                },
            },
        },
    },
}


def codes(instance: Any, **kw: Any) -> list[Code]:
    return [v.code for v in walk_config(instance, CATALOG, **kw)]


# --- the deployer's own file -------------------------------------------------------


def test_a_valid_node_file_is_clean() -> None:
    assert walk_config({"server": {"host": "127.0.0.1", "port": 4404}}, CATALOG) == []


def test_a_node_may_not_set_a_user_item() -> None:
    """The ladder is a FLOOR. `models.name` belongs to the caller, so a node that pins it
    has taken a choice away from the requestor rather than configured a default."""
    assert codes({"models": {"name": "a"}}) == [Code.SCOPE_VIOLATION]


def test_a_caller_may_set_the_user_item_the_node_could_not() -> None:
    assert walk_config({"models": {"name": "a"}}, CATALOG, actor=USER) == []


def test_an_unknown_item_is_reported_with_its_full_path() -> None:
    violations = walk_config({"server": {"prot": 4404}}, CATALOG)
    assert [v.code for v in violations] == [Code.UNKNOWN_ITEM]
    assert violations[0].pointer == "server.prot"


def test_a_wrong_type_is_reported() -> None:
    assert codes({"server": {"port": "4404"}}) == [Code.TYPE_MISMATCH]


def test_an_out_of_enum_value_is_reported() -> None:
    assert codes({"models": {"name": "zzz"}}, actor=USER) == [Code.OUT_OF_ENUM]


def test_every_mistake_is_reported_in_one_pass() -> None:
    violations = walk_config({"server": {"port": "x", "nope": 1}, "models": {"name": "a"}}, CATALOG)
    assert {v.code for v in violations} == {
        Code.TYPE_MISMATCH,
        Code.UNKNOWN_ITEM,
        Code.SCOPE_VIOLATION,
    }


# --- secrets -----------------------------------------------------------------------


def test_a_writeonly_item_takes_a_secret_reference() -> None:
    assert walk_config({"credentials": {"api_key": {"$secret": "anthropic"}}}, CATALOG) == []


def test_a_literal_in_a_writeonly_slot_is_refused() -> None:
    """THE RULE THIS EXISTS FOR: a key pasted into a node file is a key in version
    control. The message hands over the spelling that is correct."""
    violations = walk_config({"credentials": {"api_key": "sk-live-oops"}}, CATALOG)
    assert [v.code for v in violations] == [Code.NOT_SETTABLE]
    assert "$secret" in violations[0].detail


@pytest.mark.parametrize(
    "ref",
    [
        {"$secret": 123},
        {"$secret": ""},
        {"$secret": "name", "extra": 1},
    ],
)
def test_a_malformed_secret_reference_is_named_as_one(ref: dict) -> None:
    """Reported as a malformed REFERENCE, not as the wrong type — otherwise an author
    goes looking at the item's declared type instead of at what they wrote."""
    violations = walk_config({"credentials": {"api_key": ref}}, CATALOG)
    assert [v.code for v in violations] == [Code.TYPE_MISMATCH]
    assert "secret reference" in violations[0].detail


def test_a_secret_reference_on_a_non_secret_item_is_refused() -> None:
    assert codes({"server": {"host": {"$secret": "x"}}}) == [Code.TYPE_MISMATCH]


def test_an_undeclared_secret_is_reported_when_the_manifest_is_known() -> None:
    violations = walk_config(
        {"credentials": {"api_key": {"$secret": "typo"}}}, CATALOG, secrets={"anthropic"}
    )
    assert [v.code for v in violations] == [Code.UNKNOWN_ITEM]


def test_declaration_checking_is_skipped_when_no_manifest_is_in_hand() -> None:
    """`None` means "cannot check". Passing an empty set instead would report every
    reference as undeclared, which is a different and false statement."""
    assert walk_config({"credentials": {"api_key": {"$secret": "x"}}}, CATALOG) == []


def test_is_secret_ref_reports_the_claim_not_the_validity() -> None:
    assert is_secret_ref({"$secret": 123})
    assert not is_secret_ref("sk-live")


# --- open maps ---------------------------------------------------------------------


def test_deployer_chosen_keys_are_accepted() -> None:
    assert walk_config({"commands": {"/upper": ["tr", "a-z", "A-Z"]}}, CATALOG) == []


def test_a_shell_string_where_the_shape_says_array_is_refused() -> None:
    """The parent leaf's scope was fine, so without a shape check this passes — and a
    node then tries to exec a single argv token containing a whole command line."""
    violations = walk_config({"commands": {"/upper": "tr a-z A-Z"}}, CATALOG)
    assert [v.code for v in violations] == [Code.TYPE_MISMATCH]
    assert violations[0].pointer == "commands./upper"


def test_an_unknown_key_inside_a_value_shape_is_refused() -> None:
    violations = walk_config({"reads": {"/x": {"value": "hi", "typo": 1}}}, CATALOG)
    assert [v.code for v in violations] == [Code.UNKNOWN_ITEM]
    assert violations[0].pointer == "reads./x.typo"


def test_a_well_formed_value_shape_is_accepted() -> None:
    instance = {"reads": {"/x": {"file": "corpus.md", "media_type": "text/markdown"}}}
    assert walk_config(instance, CATALOG) == []


def test_a_wrong_type_inside_a_value_shape_is_refused() -> None:
    assert codes({"reads": {"/x": {"value": 5}}}) == [Code.TYPE_MISMATCH]
