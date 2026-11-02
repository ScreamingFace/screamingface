"""Configured remote-endpoint fixtures: two endpoints, two accounts, one upstream model name.

# FEATURE: hosted BYOM Unit 0 — the grant matrix every app-level test shares. Endpoint A is granted
# to accounts A and B, endpoint B to account A only, so `(A, A)`, `(A, B)` and `(B, A)` are three
# distinguishable pairs and `(B, B)` is the ungranted one.
# INVARIANT: both endpoints declare the SAME upstream model name; only the provider ID, origin and
# stored key may tell their traffic apart.
# WHY a hand-rolled TOML writer: the standard library reads TOML but cannot write it, and the
# fixtures need the same document in both forms to prove the reader adds nothing.
"""

from __future__ import annotations

import json
from typing import Any

ENDPOINT_A = "byom_" + "a" * 32
ENDPOINT_B = "byom_" + "b" * 32
ACCOUNT_A = "11111111-1111-4111-8111-111111111111"
ACCOUNT_B = "22222222-2222-4222-8222-222222222222"
ORIGIN_A = "https://endpoint-a.byom.test"
ORIGIN_B = "https://endpoint-b.byom.test"
UPSTREAM_MODEL = "researcher/model"
CHAT_PATH = "/v1/chat/completions"
ALIAS = "model_v1"


def chat_target(**overrides: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "alias": ALIAS,
        "task": "chat",
        "contract": "openai-chat-basic-v1",
        "request_path": CHAT_PATH,
        "upstream_model": UPSTREAM_MODEL,
    }
    target.update(overrides)
    return target


def endpoint(
    endpoint_id: str = ENDPOINT_A,
    *,
    origin: str = ORIGIN_A,
    accounts: tuple[str, ...] = (ACCOUNT_A,),
    enabled: bool = True,
    targets: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    table: dict[str, Any] = {
        "id": endpoint_id,
        "display_name": f"Lab endpoint {endpoint_id[-4:]}",
        "enabled": enabled,
        "origin": origin,
        "allowed_account_ids": list(accounts),
        "validation_target": ALIAS,
        "targets": targets if targets is not None else [chat_target()],
    }
    table.update(overrides)
    return table


def document(*endpoints: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"schema_version": 1, "endpoints": list(endpoints)}
    doc.update(overrides)
    return doc


def two_endpoint_document(
    *,
    a_accounts: tuple[str, ...] = (ACCOUNT_A, ACCOUNT_B),
    b_accounts: tuple[str, ...] = (ACCOUNT_A,),
    a_enabled: bool = True,
    b_enabled: bool = True,
) -> dict[str, Any]:
    return document(
        endpoint(ENDPOINT_A, origin=ORIGIN_A, accounts=a_accounts, enabled=a_enabled),
        endpoint(ENDPOINT_B, origin=ORIGIN_B, accounts=b_accounts, enabled=b_enabled),
    )


# HTTP 200 bodies that are NOT an `openai-chat-basic-v1` completion: neither readiness nor
# dispatch may accept them as a success.
MALFORMED_COMPLETIONS: dict[str, dict[str, Any]] = {
    "null-choice": {"choices": [None]},
    "number-choice": {"choices": [42]},
    "empty-choice": {"choices": [{}]},
    "string-message": {"choices": [{"message": "not-an-object"}]},
    "user-role": {"choices": [{"message": {"role": "user", "content": "x"}}]},
    "empty-message": {"choices": [{"message": {}}]},
    "missing-content": {"choices": [{"message": {"role": "assistant"}}]},
    "number-content": {"choices": [{"message": {"role": "assistant", "content": 7}}]},
    "one-bad-of-two": {
        "choices": [{"message": {"role": "assistant", "content": "."}}, {"message": None}]
    },
}
# HTTP 200 bodies that look thin but ARE a completion: the contract demands neither text nor
# an explicit role.
THIN_COMPLETIONS: dict[str, dict[str, Any]] = {
    "empty-content": {"choices": [{"message": {"role": "assistant", "content": ""}}]},
    "null-content": {"choices": [{"message": {"role": "assistant", "content": None}}]},
    "no-role": {"choices": [{"message": {"content": "x"}}]},
}


JSON_TYPE = "application/json"
FINISHED_COMPLETION: dict[str, Any] = {
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}
    ]
}


def _finished_with(*, choice: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    return {"choices": [{**FINISHED_COMPLETION["choices"][0], **(choice or {})}], **fields}


# HTTP 200 completions whose published metadata is not what an OpenAI-compatible caller may
# count on: a finish reason that is not text, token counts that are not non-negative integers.
BAD_METADATA_COMPLETIONS: dict[str, dict[str, Any]] = {
    "number-finish-reason": _finished_with(choice={"finish_reason": 17}),
    "bool-token-count": _finished_with(usage={"prompt_tokens": True}),
    "negative-token-count": _finished_with(usage={"completion_tokens": -1}),
    "float-token-count": _finished_with(usage={"total_tokens": 1e308}),
    "usage-not-an-object": _finished_with(usage="lots"),
}
# HTTP 200 completions whose metadata is well formed, absent or null: all are completions.
GOOD_METADATA_COMPLETIONS: dict[str, dict[str, Any]] = {
    "counted-usage": _finished_with(
        choice={"finish_reason": "length"},
        usage={
            "prompt_tokens": 3,
            "completion_tokens": 0,
            "total_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    ),
    "null-usage": _finished_with(usage=None),
    "null-finish-reason": _finished_with(choice={"finish_reason": None}),
}
# HTTP 200 completions that also carry an error, or a token count past what a JSON number keeps
# exactly in JavaScript: the caller would read a failure or a corrupted count as a success.
ERROR_OR_HUGE_COMPLETIONS: dict[str, dict[str, Any]] = {
    "top-level-error": _finished_with(error={"message": "failed"}),
    "top-level-error-text": _finished_with(error="failed"),
    "choice-error": _finished_with(choice={"error": {"message": "failed"}}),
    "count-past-safe-integer": _finished_with(usage={"prompt_tokens": 2**53}),
    "thousand-digit-count": _finished_with(usage={"total_tokens": int("9" * 1001)}),
}
# HTTP 200 completions at the edge of those rules: a null error is no error, and the largest
# safe integer is still a count.
EDGE_COMPLETIONS: dict[str, dict[str, Any]] = {
    "null-top-level-error": _finished_with(error=None),
    "null-choice-error": _finished_with(choice={"error": None}),
    "largest-safe-count": _finished_with(usage={"completion_tokens": 2**53 - 1}),
}
# HTTP 200 responses whose completion is well formed but whose ENVELOPE breaks the contract, as
# (Content-Type, raw body): readiness must refuse exactly what dispatch refuses.
BROKEN_ENVELOPES: dict[str, tuple[str, bytes]] = {
    "html-content-type": ("text/html", json.dumps(FINISHED_COMPLETION).encode()),
    "nan-in-usage": (
        JSON_TYPE,
        json.dumps({**FINISHED_COMPLETION, "usage": {"prompt_tokens": float("nan")}}).encode(),
    ),
    "too-deep-metadata": (
        JSON_TYPE,
        json.dumps({**FINISHED_COMPLETION, "metadata": json.loads("[" * 40 + "]" * 40)}).encode(),
    ),
}


def to_toml(doc: dict[str, Any]) -> str:
    """Render the fixture document's restricted shape as TOML text."""
    lines = [f"{key} = {_value(value)}" for key, value in doc.items() if key != "endpoints"]
    for table in doc.get("endpoints", []):
        lines += ["", "[[endpoints]]"]
        lines += [f"{key} = {_value(value)}" for key, value in table.items() if key != "targets"]
        for target in table.get("targets", []):
            lines += ["", "[[endpoints.targets]]"]
            lines += [f"{key} = {_value(value)}" for key, value in target.items()]
    return "\n".join(lines) + "\n"


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # WHY JSON quoting: a JSON string of ASCII text is a valid TOML basic string.
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"unsupported fixture value type: {type(value).__name__}")
