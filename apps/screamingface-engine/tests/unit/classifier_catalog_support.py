"""Shared fixtures of the C17 classifier catalog tests: Gateway rows and a fake Gateway."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from screamingface_engine.catalog.aigateway import AigatewayCatalogSource
from screamingface_engine.catalog.port import Credential

IDENTITY = {"X-User-Email": "alice@example.com"}
TRACE = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

TEXT_LIMITS = {
    "contract": "classifier-limits-v1",
    "max_labels": 32,
    "max_label_bytes": 64,
    "max_text_chars": 8000,
}
CHOICE_LIMITS = {
    **TEXT_LIMITS,
    "max_options": 16,
    "max_description_chars": 400,
    "max_instructions_chars": 2000,
}


def row(model: str, contracts: object, limits: object, **extra: Any) -> dict[str, Any]:
    return {
        "id": model,
        "object": "classifier",
        "result_contract": "classification-scores-v1",
        "input_contracts": contracts,
        "limits": limits,
        **extra,
    }


TEXT_NULL = row("byom_a/scalar", ["text"], None)
CHOICE = row("byom_a/choice", ["choice"], CHOICE_LIMITS)
BOTH = row("byom_b/both", ["text", "choice"], CHOICE_LIMITS, execution_access="configured")


def projected(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "input_contracts", "limits")}


def listing(*rows: object) -> dict[str, Any]:
    return {"object": "list", "data": list(rows)}


def gateway(
    answer: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request] | None = None
) -> AigatewayCatalogSource:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return answer(request)

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handle)
    )
    return AigatewayCatalogSource(client)


def json_answer(
    status: int, document: object, **headers: str
) -> Callable[[httpx.Request], httpx.Response]:
    content = json.dumps(document).encode()
    return lambda _: httpx.Response(status, content=content, headers=headers)


async def listed_rows(answer: Callable[[httpx.Request], httpx.Response]) -> list[dict[str, Any]]:
    return await gateway(answer).fetch_classifiers(Credential.derive(IDENTITY))
