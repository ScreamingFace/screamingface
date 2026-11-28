"""C9 classification entries have one strict logical-call key in the frozen-copy store."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.headers import (
    ATTEMPT_HEADER,
    BINDING_HEADER,
    MalformedCallKey,
    parse_classification_call_key,
)
from aigateway.core.frozen_copy.store import request_digest
from aigateway.core.request_cache.canonical import canonical_digest
from tests.unit.test_frozen_copy_support import (
    CASE_A,
    CASE_KEY_HEADER,
    OCCURRENCE_HEADER,
    account_id_of,
    classification_body,
    run_async,
    seed_classification_copy,
    store,
)


def _headers(**overrides: str) -> dict[str, str]:
    headers = {
        CASE_KEY_HEADER: CASE_A,
        OCCURRENCE_HEADER: "3",
        BINDING_HEADER: "router_12",
    }
    headers.update(overrides)
    return headers


def test_classification_call_key_reads_attempt_one_as_absent() -> None:
    assert parse_classification_call_key(_headers()) == (CASE_A, 3, "router_12", None)
    assert parse_classification_call_key(_headers(**{ATTEMPT_HEADER: "2"})) == (
        CASE_A,
        3,
        "router_12",
        2,
    )
    assert parse_classification_call_key(
        _headers(**{BINDING_HEADER: "router_999", ATTEMPT_HEADER: "999999999999999999"})
    ) == (CASE_A, 3, "router_999", 999999999999999999)


@pytest.mark.parametrize(
    "headers",
    [
        {CASE_KEY_HEADER: CASE_A, OCCURRENCE_HEADER: "0"},
        _headers(**{BINDING_HEADER: ""}),
        _headers(**{BINDING_HEADER: "router"}),
        _headers(**{BINDING_HEADER: "router_0"}),
        _headers(**{BINDING_HEADER: "router_01"}),
        _headers(**{BINDING_HEADER: "router_+1"}),
        _headers(**{BINDING_HEADER: "router_ 1"}),
        _headers(**{BINDING_HEADER: "router_١"}),
        _headers(**{BINDING_HEADER: "Router_1"}),
        _headers(**{BINDING_HEADER: "router_x"}),
        _headers(**{ATTEMPT_HEADER: ""}),
        _headers(**{ATTEMPT_HEADER: "0"}),
        _headers(**{ATTEMPT_HEADER: "1"}),
        _headers(**{ATTEMPT_HEADER: "02"}),
        _headers(**{ATTEMPT_HEADER: "+2"}),
        _headers(**{ATTEMPT_HEADER: "9" * 5000}),
    ],
)
def test_classification_call_key_refuses_every_noncanonical_header(
    headers: dict[str, str],
) -> None:
    with pytest.raises(MalformedCallKey):
        parse_classification_call_key(headers)


def test_classification_digest_is_the_exact_c9_preimage() -> None:
    body = classification_body()

    assert request_digest("classify", body, binding="router_2") == canonical_digest(
        {"kind": "classify", "request": body, "binding": "router_2"}
    )
    assert request_digest("classify", body, 2, binding="router_2") == canonical_digest(
        {"kind": "classify", "request": body, "binding": "router_2", "attempt": 2}
    )


def test_classification_requires_a_binding_and_other_kinds_refuse_one() -> None:
    body = classification_body()

    with pytest.raises(ValueError, match="binding"):
        request_digest("classify", body)
    with pytest.raises(ValueError, match="Attempt 1"):
        request_digest("classify", body, 1, binding="router_1")
    for binding in ("router_0", "router_01", "router_+1", "router_ 1", "router_١"):
        with pytest.raises(ValueError, match="binding"):
            request_digest("classify", body, binding=binding)
    for kind in ("chat", "tool"):
        with pytest.raises(ValueError, match="binding"):
            request_digest(kind, body, binding="router_1")


def test_chat_and_tool_digest_preimages_stay_byte_identical() -> None:
    request = {"value": "same"}

    for kind in ("chat", "tool"):
        assert request_digest(kind, request) == canonical_digest({"kind": kind, "request": request})
        assert request_digest(kind, request, 2) == canonical_digest(
            {"kind": kind, "request": request, "attempt": 2}
        )


def _response(marker: str) -> dict[str, Any]:
    return {"model": "hf-inference/sentiment", "scores": [{"label": marker, "score": 1.0}]}


def test_store_separates_binding_occurrence_and_attempt(
    authenticated_client: TestClient,
) -> None:
    client = authenticated_client
    body = classification_body()
    copy_id = seed_classification_copy(
        client,
        account_id_of(client),
        [
            (CASE_A, 0, "router_1", None, body, _response("binding-1"), 200),
            (CASE_A, 0, "router_2", None, body, _response("binding-2"), 200),
            (CASE_A, 1, "router_1", None, body, _response("occurrence-1"), 200),
            (CASE_A, 0, "router_1", 2, body, _response("attempt-2"), 200),
        ],
    )

    async def _read(binding: str, occurrence: int, attempt: int | None) -> str | None:
        frozen = store()
        copy = await frozen.get(UUID(copy_id))
        assert copy is not None
        entry = await frozen.find(
            copy,
            "classify",
            body,
            attempt=attempt,
            case_key=CASE_A,
            occurrence=occurrence,
            binding=binding,
        )
        return None if entry is None else entry.response_json["scores"][0]["label"]

    assert run_async(client, lambda: _read("router_1", 0, None)) == "binding-1"
    assert run_async(client, lambda: _read("router_2", 0, None)) == "binding-2"
    assert run_async(client, lambda: _read("router_1", 1, None)) == "occurrence-1"
    assert run_async(client, lambda: _read("router_1", 0, 2)) == "attempt-2"
    assert run_async(client, lambda: _read("router_1", 0, 3)) is None
