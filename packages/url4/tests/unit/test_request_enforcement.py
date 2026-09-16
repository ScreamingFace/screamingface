"""Request-time enforcement: the node never answers 200 to config it did not apply.

STORY: as a caller I fetch a mount's schema, see which items are mine, and send them. If
they are accepted the node applies them; if they are not, it TELLS me. What it must never
do is answer 200 having silently dropped them — my eval run would then be wrong and
nothing would have said so.

THE BUG THIS ENCODES: before this existed, `URL4-Config-*` headers were read by nothing.
A caller sending `credentials.api_key` got a 200. The key was not used, so nothing bad
happened — but the node had said "I did what you asked" to a request that tried to
override a credential, with no log line and no signal to anyone.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import pytest

from url4.cli._serve import ServeConfig, build_asgi_app, build_node
from url4.discovery import Discovery, Mount
from url4.discovery.request import Applied, addressed_routes, read_request_config

CMDS = {"/echo": ("cat",)}

SERVED: dict[str, Any] = {
    "$id": "url4-config",
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
                    "description": "Model id.",
                    # Already narrowed for THIS caller — Opus is a real model this
                    # profile may not use.
                    "enum": ["anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"],
                }
            },
        },
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "temperature": {"type": "number", "x-scope": "user", "description": "Temp."}
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
    },
}

HAIKU = "anthropic/claude-haiku-4-5"
LIVE = Mount(path="/claude-fast", endpoint_id="node-anthropic", served_schema=SERVED)
DEAD = Mount(path="/vendor", endpoint_id="vendor", served_schema=None)


# --- which routes an expression addresses -----------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(/claude-fast)!'summarise'", {"/claude-fast"}),
        ("/claude-fast(ctx)!'go'", {"/claude-fast"}),
        ("(/claude-fast(a)!'x',/gpt(b)!'y')!'reduce'", {"/claude-fast", "/gpt"}),
        ("('literal')!'x'", set()),
    ],
)
def test_both_addressing_forms_are_collected(expression: str, expected: set[str]) -> None:
    """`/x(ctx)!'i'` CALLS the route; `(/x)!'i'` reads it as a SOURCE. Collecting only
    the call form would let a caller address a mount the other way and have their config
    silently dropped — the exact failure this module prevents."""
    assert addressed_routes(expression) == expected


def test_an_unparseable_expression_addresses_nothing() -> None:
    """The node parses it again and owns the grammar error; this layer must not race it
    to a worse message."""
    assert addressed_routes("!!! not an expression") == frozenset()


# --- reading a request's config ----------------------------------------------------


def hdr(**items: str) -> list[tuple[bytes, bytes]]:
    return [(f"url4-config-{k.replace('__', '.')}".encode(), v.encode()) for k, v in items.items()]


def test_no_config_headers_is_the_ordinary_case() -> None:
    result = read_request_config([(b"host", b"x")], "(/claude-fast)!'x'", [LIVE])
    assert result == Applied(values={})
    assert not result.rejected


def test_values_the_caller_may_set_are_applied() -> None:
    result = read_request_config(
        hdr(models__name=HAIKU, parameters__temperature="0"),
        "/claude-fast(ctx)!'summarise'",
        [LIVE],
    )
    assert not result.rejected
    assert result.values == {"models.name": HAIKU, "parameters.temperature": 0.0}


def test_a_secret_is_refused() -> None:
    result = read_request_config(
        hdr(credentials__api_key="sk-attacker"), "/claude-fast(c)!'x'", [LIVE]
    )
    assert result.rejected
    codes = {v["code"] for v in result.problem["violations"]}
    assert codes == {"config-not-settable"}


def test_a_model_outside_the_callers_enum_is_refused() -> None:
    result = read_request_config(
        hdr(models__name="anthropic/claude-opus-4-8"), "/claude-fast(c)!'x'", [LIVE]
    )
    assert result.rejected
    assert result.problem["violations"][0]["code"] == "config-out-of-enum"


def test_config_with_no_mounted_endpoint_addressed_is_refused() -> None:
    """There is no schema to judge it against, so the node cannot know whether these
    values are the caller's to set. Refusing beats guessing."""
    result = read_request_config(hdr(models__name=HAIKU), "(/echo)!'x'", [LIVE])
    assert result.rejected
    assert "addresses no mounted endpoint" in result.problem["violations"][0]["detail"]


def test_config_on_a_multi_mount_expression_is_refused_as_ambiguous() -> None:
    """Config is per-ENDPOINT. Applying one endpoint's values to another is a silent
    wrong answer, which is worse than declining."""
    other = Mount(path="/gpt", endpoint_id="node-codex", served_schema=SERVED)
    result = read_request_config(
        hdr(models__name=HAIKU), "(/claude-fast(a)!'x',/gpt(b)!'y')!'r'", [LIVE, other]
    )
    assert result.rejected
    assert "ambiguous" in result.problem["violations"][0]["detail"]


def test_config_for_an_unavailable_mount_is_refused() -> None:
    result = read_request_config(hdr(models__name=HAIKU), "/vendor(c)!'x'", [DEAD])
    assert result.rejected
    assert "unavailable" in result.problem["violations"][0]["detail"]


def test_every_violation_is_reported_at_once() -> None:
    result = read_request_config(
        hdr(credentials__api_key="sk-x", models__name="anthropic/claude-opus-4-8"),
        "/claude-fast(c)!'x'",
        [LIVE],
    )
    assert {v["pointer"] for v in result.problem["violations"]} == {
        "credentials.api_key",
        "models.name",
    }


# --- through the real ASGI app -----------------------------------------------------


def _app(mounts: list[Mount]):
    config = ServeConfig(commands=CMDS)
    config.validate()

    async def resolve(_caller: str | None):
        return mounts

    return build_asgi_app(build_node(config), config, discovery=Discovery("http://n", resolve))


def _call(app, expression: str, headers: list[tuple[bytes, bytes]] | None = None):
    import asyncio

    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1",
        "query_string": urlencode({"q": expression}).encode(),
        "headers": headers or [],
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def test_a_request_without_config_is_untouched() -> None:
    """Enforcement must cost nothing for the ordinary request."""
    status, _, _ = _call(_app([LIVE]), "(/echo(hi)!'go')!''")
    assert status == 200


def test_a_smuggled_credential_no_longer_gets_a_200() -> None:
    """THE HOLE THIS CLOSES. This request used to answer 200 with the header ignored."""
    status, headers, body = _call(
        _app([LIVE]), "/claude-fast(c)!'x'", hdr(credentials__api_key="sk-attacker")
    )
    assert status == 400
    assert headers[b"content-type"] == b"application/problem+json"
    problem = json.loads(body)
    assert problem["violations"][0]["pointer"] == "credentials.api_key"


def test_an_out_of_enum_model_gets_a_400() -> None:
    status, _, body = _call(
        _app([LIVE]), "/claude-fast(c)!'x'", hdr(models__name="anthropic/claude-opus-4-8")
    )
    assert status == 400
    assert json.loads(body)["violations"][0]["code"] == "config-out-of-enum"


def test_valid_config_is_refused_as_not_yet_forwardable_rather_than_silently_dropped() -> None:
    """HONEST GAP. These values ARE the caller's to set and the node validated them — but
    forwarding config to a mounted endpoint is the composer's job and does not exist yet.
    A 501 says so. A 200 would be the same silent lie in the other direction."""
    status, _, body = _call(_app([LIVE]), "/claude-fast(c)!'x'", hdr(models__name=HAIKU))
    assert status == 501
    assert "cannot yet FORWARD" in json.loads(body)["violations"][0]["detail"]


def test_a_node_with_no_mounts_still_refuses_config() -> None:
    """It has no schema to judge against, so it cannot honour the values — and must not
    claim to."""
    status, _, _ = _call(_app([]), "(/echo(hi)!'go')!''", hdr(models__name=HAIKU))
    assert status == 400
