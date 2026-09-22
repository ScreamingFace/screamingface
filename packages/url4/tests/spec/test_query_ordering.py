"""`OME-507` cycle 1 — ``q=`` is always the last query parameter.

# FEATURE: `query-string = *( query-param "&" ) "q=" expression-body` — the
# expression-bearing parameter closes the query string, so everything after
# `q=` belongs to the EXPRESSION, never to the parameter list.
#
# WHY this had to be enforced: the two sides disagreed. The grammar already
# implements "q= is last" by construction — `_parse_expr_canonical` takes the
# whole remainder after the `q=` body as the intent tail — so it REJECTS
# `/p?q=(a)!'go'&tone=formal` ("unexpected text after quoted value"). The wire
# splitter meanwhile accepted the same string and produced a `tone` param. A
# node therefore honoured over HTTP what it refused in text — the split-rule
# defect `OME-501` removed. Rejecting at the wire restores one rule.
#
# INVARIANT: mandatoriness is scoped to THIS production. A query with no `q=`
# at all is a `relative-uri` data fetch (`[ "?" query-tail ]`), a different
# production — data routes need no exemption and are untouched.
"""

from __future__ import annotations

import pytest

from url4.core.errors import ParseError
from url4.wire.subrequest import extract_expression_params

# --- q= last ---------------------------------------------------------------------


def test_params_before_q_are_accepted() -> None:
    params, q = extract_expression_params("tone=formal&quorum=2&q=(a)!'go'")
    assert params == {"tone": "formal", "quorum": "2"}
    assert q == "(a)!'go'"


@pytest.mark.parametrize(
    "query",
    [
        "q=(a)!'go'&tone=formal",
        "tone=formal&q=(a)!'go'&quorum=2",
        "q=(a)!'go'&flag",
    ],
)
def test_a_parameter_after_q_is_rejected(query: str) -> None:
    with pytest.raises(ParseError, match="last"):
        extract_expression_params(query)


def test_duplicate_q_is_rejected() -> None:
    # The production names exactly one `q=`; a second silently overwrote it.
    with pytest.raises(ParseError, match="last"):
        extract_expression_params("q=(a)!'x'&q=(b)!'y'")


# --- a nested & inside the expression is NOT a parameter boundary ------------------


def test_nested_ampersand_does_not_count_as_a_following_parameter() -> None:
    # Depth-0 only: the `&` inside the nested expression belongs to that value.
    params, q = extract_expression_params("q=(https://a?x=1&y=2)!'go'")
    assert params == {}
    assert q == "(https://a?x=1&y=2)!'go'"


def test_processor_expression_before_q_still_works() -> None:
    params, q = extract_expression_params("processor=(p='/gpt4')!'$p'&q=(a)!'go'")
    assert params["processor"] == "(p='/gpt4')!'$p'"
    assert q == "(a)!'go'"


# --- no q= at all is a data query (relative-uri), untouched -----------------------


@pytest.mark.parametrize("query", ["a=1&b=2", "limit=10&sort=asc", "", "flag"])
def test_query_without_q_is_a_data_query(query: str) -> None:
    _params, q = extract_expression_params(query)
    assert q is None


def test_data_route_with_a_query_string_is_still_served() -> None:
    import asyncio

    from url4.peer.server import Url4Node

    node = Url4Node("n")
    node.data("/api/rows", "DATA")
    assert asyncio.run(node.fetch("/api/rows?limit=10&sort=asc", relative=True)) == "DATA"


# --- over HTTP the violation is a 400, matching the text-side rejection ------------


def test_wire_q_not_last_is_a_400() -> None:
    import asyncio

    from url4.peer.server import Url4Node

    node = Url4Node("n", eval_path="/v1")
    node.endpoint("/claude")(lambda request: f"claude:{request.intent}")

    async def _get(target: str) -> int:
        status: dict[str, int] = {}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        scope = {
            "type": "http",
            "method": "GET",
            "path": target.partition("?")[0],
            "query_string": target.partition("?")[2].encode(),
        }
        await node.asgi()(scope, None, send)
        return status["code"]

    ok = asyncio.run(_get("/v1?q=(/claude(a)!'x')!'go'"))
    assert ok == 200
    bad = asyncio.run(_get("/v1?q=(/claude(a)!'x')!'go'&tone=formal"))
    assert bad == 400
