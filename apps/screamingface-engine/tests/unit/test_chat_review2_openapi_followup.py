"""The OpenAPI follow-up of the chat endpoint (review round 2, FX-4).

RR-S9, RR-S10 and RR-S15 of the TDD table in docs/spec/2026-11-17-engine-openai-chat-endpoint/
prd/review-round-2.md: the 503 entry names each code and the Retry-After rule, the Access scheme
sits on the chat operation only, the default of `requires_identity` is hosted, and the 408 entry
names the limit of a large body.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from screamingface_engine.app import create_app
from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.chat_errors import from_problem
from screamingface_engine.rest.chat_openapi import set_chat_security
from screamingface_engine.rest.runs_boundary import requires_identity

_PATH = "/v1/chat/completions"
_RETRY_CODES = (
    "run_failed",
    "worker_draining",
    "server_restarting",
    "chat_input_unavailable",
    "catalog_unavailable",
    "queue_unavailable",
)


def _responses() -> dict[str, Any]:
    responses: dict[str, Any] = create_app().openapi()["paths"][_PATH]["post"]["responses"]
    return responses


def test_503_names_internal_error_and_each_code_with_retry_after() -> None:
    desc: str = _responses()["503"]["description"]
    assert "`internal_error`" in desc
    after = desc.split("sends `Retry-After`", 1)[1]
    for code in _RETRY_CODES:
        assert f"`{code}`" in after

    err = from_problem(ProblemException(status=503, title="Service Unavailable", detail="x"))
    assert (err.status, err.code) == (503, "internal_error")


def test_chat_security_is_set_on_the_chat_path_only() -> None:
    schema: dict[str, Any] = {
        "paths": {
            _PATH: {"post": {"tags": ["Chat"]}},
            "/v1/models": {"get": {"tags": ["Chat"]}},
        }
    }
    set_chat_security(schema, hosted=True)
    assert schema["paths"][_PATH]["post"]["security"] == [{"CloudflareAccess": []}]
    assert "security" not in schema["paths"]["/v1/models"]["get"]


def test_requires_identity_defaults_to_true() -> None:
    assert requires_identity(SimpleNamespace(state=SimpleNamespace())) is True
    flagged = SimpleNamespace(state=SimpleNamespace(runs_require_identity=False))
    assert requires_identity(flagged) is False


def test_408_says_the_limit_changes_at_the_parse_place() -> None:
    desc: str = _responses()["408"]["description"]
    assert "`request_timeout`" in desc
    assert "parse place" in desc
    assert "from that time" in desc
