"""The served OpenAPI entry of POST /v1/chat/completions matches the route (review round 2).

RR-20 of the TDD table in docs/spec/2026-11-17-engine-openai-chat-endpoint/prd/review-round-2.md
(RR-S15): the chat operation declares each status and code that the route can answer, the
`Retry-After` and `x-should-retry` headers, the `screamingface` object with
`ignored_parameters` and `final_step.cached`, and in hosted mode the Access header as its
security scheme.

WHY the statuses come from the code: a hand list in the test goes stale the same way as the
document. The test reads the `ChatError(<status>, <code>)` calls of `rest/chat_*.py`, the row
tables of the terminal answer and of the wait, and the statuses of `from_problem`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

from screamingface_engine.app import create_app
from screamingface_engine.chat import recipe as chat_recipe
from screamingface_engine.rest import chat_answer, chat_wait
from screamingface_engine.rest.chat_errors import FIXED_MESSAGES, restart_retry_after

_PATH = "/v1/chat/completions"
_REST = Path(chat_answer.__file__).parent
# WHY: 499 names a client that left in the metrics; nobody reads that answer.
_METRICS_ONLY = {499}
# WHY by hand: `from_problem` re-envelopes a scheduler problem. A full runner is 429 and a broken
# queue is 503, both with Retry-After; any other problem keeps its status with `internal_error`,
# and 409 is the one that a start can raise (a conflict of the topic).
_FROM_PROBLEM: set[tuple[int, str, bool]] = {
    (429, "overloaded", True),
    (503, "queue_unavailable", True),
    (409, "internal_error", False),
}
# WHY: a code of a failed run that the Engine vouches for passes as the body code (502).
_VOUCHED = "a_vouched_code"

type _Raise = tuple[int, str | None, bool]


def _op(*, hosted: bool | None = None) -> dict[str, Any]:
    app = create_app()
    if hosted is not None:
        app.state.runs_require_identity = hosted
    return app.openapi()["paths"][_PATH]["post"]


def _literal(node: ast.expr | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _chat_error(call: ast.Call) -> _Raise | None:
    """(status, code, sends Retry-After) of one `ChatError(<int>, ...)` call, else None."""
    name = call.func.id if isinstance(call.func, ast.Name) else None
    status = _literal(call.args[0]) if call.args else None
    if name != "ChatError" or not isinstance(status, int):
        return None
    code = _literal(call.args[1]) if len(call.args) > 1 else None
    retry = any(
        k.arg == "retry_after" and not (isinstance(k.value, ast.Constant) and k.value.value is None)
        for k in call.keywords
    )
    return status, code if isinstance(code, str) else None, retry


def _scanned() -> set[_Raise]:
    """Each literal `ChatError` call of the route modules."""
    raised: set[_Raise] = set()
    for path in sorted(_REST.glob("chat_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            found = _chat_error(node) if isinstance(node, ast.Call) else None
            if found is not None:
                raised.add(found)
    return raised


def _recipe_codes() -> set[str]:
    """The codes of `RecipeRefusal(<code>, ...)`; the route answers each one as a 400."""
    tree = ast.parse(Path(cast(str, chat_recipe.__file__)).read_text())
    return {
        code
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RecipeRefusal"
        and node.args
        and isinstance(code := _literal(node.args[0]), str)
    }


def _rows() -> set[_Raise]:
    """The rows of the terminal table and of the wait, with their Retry-After."""
    rows = [
        *chat_answer._CODE_ROWS.values(),
        *chat_answer._TRANSIENT_ROWS.values(),
        *chat_answer._STATE_ROWS.values(),
        *chat_wait.WAIT_ROWS.values(),
        chat_answer._row("failed", _VOUCHED, _VOUCHED, True),
        chat_answer._row("failed", None, None, None),
    ]
    return {(s, c, restart_retry_after(s, retry) is not None) for s, c, retry in rows}


def _answers() -> set[_Raise]:
    """Each (status, code, Retry-After) that the route can answer, 499 left out."""
    recipe = {(400, code, False) for code in _recipe_codes()}
    found = _scanned() | _rows() | recipe | {(s, c, r) for s, c, r in _FROM_PROBLEM}
    return {row for row in found if row[0] not in _METRICS_ONLY}


def _error_statuses(op: dict[str, Any]) -> set[int]:
    return {int(key) for key in op["responses"] if key.isdigit() and int(key) >= 400}


def _object(schema: dict[str, Any]) -> dict[str, Any]:
    """The object branch of a nullable schema."""
    branches = cast(list[dict[str, Any]], schema.get("anyOf", [schema]))
    return next(branch for branch in branches if branch.get("type") == "object")


def test_openapi_declares_each_status_the_route_can_answer() -> None:
    """Each status that the code can raise is declared, and each declared status is reachable."""
    reachable = {status for status, _code, _retry in _answers()}
    declared = _error_statuses(_op())

    assert 408 in reachable
    assert 499 not in declared
    assert reachable <= declared, sorted(reachable - declared)
    assert declared <= reachable, sorted(declared - reachable)


def test_each_code_of_the_route_is_named_in_its_status_description() -> None:
    """Each fixed body code and each row code is named under each status that can carry it."""
    responses = _op()["responses"]
    pairs = {(status, code) for status, code, _retry in _answers() if code not in (None, _VOUCHED)}
    named = {code for _status, code in pairs}

    assert set(FIXED_MESSAGES) - {"client_disconnected"} <= named
    assert {(502, "result_too_large"), (408, "request_timeout")} <= pairs
    assert {(500, "chat_input_unavailable"), (503, "chat_input_unavailable")} <= pairs
    for status, code in sorted(pairs, key=str):
        assert f"`{code}`" in responses[str(status)]["description"], (status, code)
    assert "vouches" in responses["502"]["description"]


def test_retry_headers_are_declared() -> None:
    """x-should-retry is on each error answer; Retry-After is on each one that can send it."""
    op = _op()
    with_retry = {status for status, _code, retry in _answers() if retry}

    assert with_retry == {429, 503}
    for status in _error_statuses(op):
        headers = op["responses"][str(status)].get("headers", {})
        assert "x-should-retry" in headers, status
        assert ("Retry-After" in headers) == (status in with_retry), status
    assert op["responses"]["429"]["headers"]["Retry-After"]["schema"]["type"] == "integer"
    assert op["responses"]["400"]["headers"]["x-should-retry"]["schema"]["enum"] == [
        "true",
        "false",
    ]


def test_screamingface_schema_has_ignored_parameters_and_final_step_cached() -> None:
    """The 200 JSON schema shows the two keys that are absent when they carry nothing."""
    schema = _op()["responses"]["200"]["content"]["application/json"]["schema"]
    info = schema["properties"]["screamingface"]
    ignored = info["properties"]["ignored_parameters"]
    final_step = _object(info["properties"]["final_step"])
    cached = final_step["properties"]["cached"]

    assert {"id", "choices", "usage", "screamingface"} <= set(schema["required"])
    assert ignored["type"] == "array"
    assert ignored["items"] == {"type": "string"}
    assert "absent" in ignored["description"].casefold()
    assert "ignored_parameters" not in info.get("required", [])
    assert cached["type"] == "boolean"
    assert cached["const"] is True
    assert "absent" in cached["description"].casefold()
    assert "cached" not in final_step.get("required", [])
    assert "$ref" not in str(schema)


def test_hosted_mode_uses_the_access_scheme_not_the_capability_scheme() -> None:
    """Hosted: the chat operation names the Access header; the capability JWT stays on `/`."""
    app = create_app()
    app.state.runs_require_identity = True
    schema = app.openapi()
    op = schema["paths"][_PATH]["post"]
    schemes = schema["components"]["securitySchemes"]

    assert op["security"] == [{"CloudflareAccess": []}]
    assert schemes["CloudflareAccess"] == {
        "type": "apiKey",
        "in": "header",
        "name": "Cf-Access-Token",
        "description": schemes["CloudflareAccess"]["description"],
    }
    assert "URL4Capability" not in str(op["security"])
    assert schema["paths"]["/"]["get"]["security"] == [{"URL4Capability": []}]


def test_local_mode_has_no_security_on_the_chat_operation() -> None:
    """Local mode is single-user: the chat operation needs no credential."""
    op = _op(hosted=False)

    assert "security" not in op
