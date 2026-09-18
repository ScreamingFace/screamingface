"""Where user-scope config values travel, and what happens when they may not (D1).

STORY: as a client I fetch `/.well-known/url4-config/<mount>`, see which items are MINE to
set, and send them — on a WebSocket attach frame if I have one, as `URL4-Config-*` headers
if I don't. Both are valid. A value I am not allowed to set is REFUSED with an RFC 9457
problem naming the item, never silently dropped and never silently honoured.
"""

from __future__ import annotations

import pytest

from url4.discovery.carrier import (
    CarrierError,
    coerce,
    from_attach_frame,
    from_headers,
    missing_underscored,
)
from url4.discovery.problem import PROBLEM_TYPE, config_rejected
from url4.discovery.scope import Code, enforce, resolve_item, settable_by

# The `/claude-fast` schema as the node serves it to profile "acme": the enum is already
# narrowed to what that credential may use, which is the whole point of serving per caller.
SCHEMA = {
    "$id": "url4-config",
    "type": "object",
    "properties": {
        "models": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "x-scope": "user",
                    "enum": ["anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"],
                }
            },
        },
        "parameters": {
            "type": "object",
            "properties": {
                "temperature": {"type": "number", "x-scope": "user"},
                "max_tokens": {"type": "integer", "x-scope": "user"},
                "stream": {"type": "boolean", "x-scope": "user"},
                "top_p": {"type": "number", "x-scope": "user"},
                "response_format": {"type": "object", "x-scope": "user"},
            },
        },
        "credentials": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "x-scope": "node", "writeOnly": True},
                "base_url": {"type": "string", "x-scope": "node"},
            },
        },
        "endpoint": {
            "type": "object",
            "properties": {"build_id": {"type": "string", "x-scope": "system", "readOnly": True}},
        },
    },
}

HAIKU = "anthropic/claude-haiku-4-5"


# --- the ladder -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actor", "item_scope", "allowed"),
    [
        ("user", "user", True),
        ("user", "node", False),
        ("user", "system", False),
        ("node", "node", True),
        ("node", "user", False),
    ],
)
def test_the_scope_is_a_floor_not_a_range(actor: str, item_scope: str, allowed: bool) -> None:
    """An item names the MOST PERMISSIVE level allowed to set it. A `node` item is the
    deployer's, so a caller may not set it — and a `user` item is the caller's, so the
    node does not set it at request time either."""
    assert settable_by(actor, item_scope) is allowed


# --- resolving an item ------------------------------------------------------------


def test_a_dotted_path_reaches_a_leaf() -> None:
    item = resolve_item(SCHEMA, "models.name")
    assert item is not None and item["x-scope"] == "user"


def test_a_namespace_is_not_an_item() -> None:
    # `models` has properties and no x-scope, so it is a group. Setting a group is
    # meaningless — only leaves carry values.
    assert resolve_item(SCHEMA, "models") is None


def test_a_path_inside_a_structured_leaf_does_not_resolve() -> None:
    """`response_format` carries x-scope, so it is a LEAF whose value happens to be an
    object. Its interior is the value, not more items."""
    assert resolve_item(SCHEMA, "parameters.response_format") is not None
    assert resolve_item(SCHEMA, "parameters.response_format.type") is None


def test_an_unknown_path_resolves_to_nothing() -> None:
    assert resolve_item(SCHEMA, "parameters.nonesuch") is None


# --- enforcement ------------------------------------------------------------------


def test_user_scope_values_are_accepted() -> None:
    assert enforce({"models.name": HAIKU, "parameters.temperature": 0}, SCHEMA) == []


def test_a_node_scope_item_is_refused() -> None:
    (v,) = enforce({"credentials.base_url": "http://evil.example"}, SCHEMA)
    assert v.code is Code.SCOPE_VIOLATION
    assert v.pointer == "credentials.base_url"


def test_a_secret_is_refused_as_a_secret_not_as_a_scope_error() -> None:
    """A caller sending `api_key` is trying to inject a credential. The message should say
    so rather than talk about the ladder."""
    (v,) = enforce({"credentials.api_key": "sk-injected"}, SCHEMA)
    assert v.code is Code.NOT_SETTABLE
    assert "writeOnly" in v.detail


def test_a_readonly_system_item_is_refused() -> None:
    (v,) = enforce({"endpoint.build_id": "forged"}, SCHEMA)
    assert v.code is Code.NOT_SETTABLE


def test_an_unknown_item_is_refused_rather_than_ignored() -> None:
    """Silently dropping it would tell the caller their value was accepted."""
    (v,) = enforce({"parameters.nonesuch": 1}, SCHEMA)
    assert v.code is Code.UNKNOWN_ITEM


def test_a_value_outside_the_callers_enum_is_refused() -> None:
    # Opus is a real model — just not one THIS profile may use. The enum was narrowed for
    # this caller, and the refusal is what makes that narrowing mean something.
    (v,) = enforce({"models.name": "anthropic/claude-opus-4-8"}, SCHEMA)
    assert v.code is Code.OUT_OF_ENUM


def test_a_wrong_type_is_refused() -> None:
    (v,) = enforce({"parameters.temperature": "hot"}, SCHEMA)
    assert v.code is Code.TYPE_MISMATCH
    assert "number" in v.detail


def test_true_does_not_satisfy_an_integer() -> None:
    """`bool` subclasses `int` in Python; the wire says they are different types."""
    (v,) = enforce({"parameters.max_tokens": True}, SCHEMA)
    assert v.code is Code.TYPE_MISMATCH


def test_every_violation_is_reported_in_one_pass() -> None:
    """Four mistakes should cost one round trip, not four."""
    violations = enforce(
        {
            "credentials.api_key": "sk-x",
            "models.name": "anthropic/claude-opus-4-8",
            "parameters.temperature": "hot",
            "parameters.nonesuch": 1,
        },
        SCHEMA,
    )
    assert {v.code for v in violations} == {
        Code.NOT_SETTABLE,
        Code.OUT_OF_ENUM,
        Code.TYPE_MISMATCH,
        Code.UNKNOWN_ITEM,
    }


# --- carrier: the attach frame ----------------------------------------------------


def test_an_absent_config_member_is_no_values_not_an_error() -> None:
    assert from_attach_frame({"url4": "(/claude-fast)!'x'"}) == {}


def test_the_attach_frame_carries_native_types() -> None:
    frame = {"url4": "(/x)!'y'", "config": {"parameters.temperature": 0.7}}
    assert from_attach_frame(frame) == {"parameters.temperature": 0.7}


def test_a_config_member_of_the_wrong_shape_is_malformed() -> None:
    with pytest.raises(CarrierError, match="must be an object"):
        from_attach_frame({"config": ["temperature", 0]})


# --- carrier: headers -------------------------------------------------------------


def test_headers_are_collected_by_prefix() -> None:
    values = from_headers(
        [(b"host", b"node.example"), (b"URL4-Config-models.name", HAIKU.encode())]
    )
    assert values == {"models.name": HAIKU}


def test_the_dotted_path_survives_verbatim() -> None:
    """`.` and `_` are both legal in an HTTP field name (RFC 9110 token), so no flattening
    is needed and two items cannot collide into one header name."""
    values = from_headers([(b"url4-config-parameters.top_p", b"0.9")])
    assert "parameters.top_p" in values


def test_a_bare_prefix_header_names_no_item() -> None:
    with pytest.raises(CarrierError, match="names no item"):
        from_headers([(b"URL4-Config-", b"x")])


# --- coercion: the price of a string-only carrier ---------------------------------


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("parameters.temperature", "0.7", 0.7),
        ("parameters.max_tokens", "512", 512),
        ("parameters.stream", "true", True),
        ("parameters.stream", "false", False),
        ("models.name", HAIKU, HAIKU),
        ("parameters.response_format", '{"type":"json"}', {"type": "json"}),
    ],
)
def test_a_header_value_is_typed_from_the_schema(path: str, text: str, expected) -> None:
    typed, unparseable = coerce({path: text}, SCHEMA)
    assert typed[path] == expected
    assert unparseable == []


def test_an_unparseable_value_keeps_its_string_so_enforce_names_the_real_type() -> None:
    """Left as-is on purpose: `enforce` then reports a type mismatch naming the DECLARED
    type, so both carriers produce the same error vocabulary."""
    typed, unparseable = coerce({"parameters.temperature": "hot"}, SCHEMA)
    assert typed["parameters.temperature"] == "hot"
    assert unparseable == ["parameters.temperature"]
    (v,) = enforce(typed, SCHEMA)
    assert v.code is Code.TYPE_MISMATCH


def test_only_the_json_spellings_of_a_boolean_are_accepted() -> None:
    """Accepting "yes"/"1" would make headers lenient where the attach frame is strict."""
    _, unparseable = coerce({"parameters.stream": "yes"}, SCHEMA)
    assert unparseable == ["parameters.stream"]


def test_an_unknown_item_passes_coercion_untouched() -> None:
    """One mistake should be one error. `enforce` is what refuses it."""
    typed, unparseable = coerce({"parameters.nonesuch": "x"}, SCHEMA)
    assert typed == {"parameters.nonesuch": "x"} and unparseable == []


# --- the two carriers must agree --------------------------------------------------


@pytest.mark.parametrize(
    ("frame_value", "header_text"),
    [
        (HAIKU, HAIKU),
        (0.7, "0.7"),
        (512, "512"),
        (True, "true"),
    ],
)
def test_both_carriers_produce_the_same_payload(frame_value, header_text: str) -> None:
    """THE POINT OF THE DESIGN. Two envelopes, one payload — so `enforce` runs over one
    shape and the transports cannot disagree about what was sent."""
    path = {
        str: "models.name",
        float: "parameters.temperature",
        int: "parameters.max_tokens",
        bool: "parameters.stream",
    }[type(frame_value)]

    via_frame = from_attach_frame({"config": {path: frame_value}})
    raw = [(f"url4-config-{path}".encode(), header_text.encode())]
    via_headers, _ = coerce(from_headers(raw), SCHEMA)

    assert via_frame == via_headers
    assert enforce(via_frame, SCHEMA) == enforce(via_headers, SCHEMA) == []


def test_both_carriers_are_refused_identically() -> None:
    bad = "anthropic/claude-opus-4-8"
    frame = from_attach_frame({"config": {"models.name": bad}})
    headers, _ = coerce(from_headers([(b"url4-config-models.name", bad.encode())]), SCHEMA)
    assert enforce(frame, SCHEMA) == enforce(headers, SCHEMA)


# --- the problem response ---------------------------------------------------------


def test_the_problem_lists_every_violation() -> None:
    violations = enforce(
        {"credentials.api_key": "sk-x", "models.name": "anthropic/claude-opus-4-8"}, SCHEMA
    )
    body = config_rejected(violations, instance="/v1")
    assert body["type"] == PROBLEM_TYPE
    assert body["status"] == 400
    assert body["instance"] == "/v1"
    assert {v["pointer"] for v in body["violations"]} == {
        "credentials.api_key",
        "models.name",
    }


def test_a_single_violation_reads_as_itself() -> None:
    body = config_rejected(enforce({"parameters.temperature": "hot"}, SCHEMA))
    assert "number" in body["detail"]


# --- the nginx hazard -------------------------------------------------------------


def test_underscored_user_items_can_be_listed_for_an_operator() -> None:
    """nginx DROPS headers with underscores unless `underscores_in_headers on`, so
    `parameters.top_p` vanishes and the request quietly runs on the default. Nothing can
    distinguish dropped from not-sent — this only gives an operator the candidates."""
    assert missing_underscored({}, SCHEMA) == [
        "parameters.max_tokens",
        "parameters.response_format",
        "parameters.top_p",
    ]
    assert "parameters.top_p" not in missing_underscored({"parameters.top_p": 0.9}, SCHEMA)
