"""An endpoint that declares only classifiers is still a provider its granted accounts can find.

# FEATURE: hosted BYOM Unit 3 — the provider listing keeps a provider that has chat models or
# classifiers, so a classifier-only endpoint can be connected like any other.
# INVARIANT: every other provider's row is unchanged, and the grant still decides who sees it.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from .classifier_upstream import classifier_only_document, started
from .conftest import Harness, tenant_headers
from .fixtures import ACCOUNT_A, ACCOUNT_B, ENDPOINT_A


def _rows(client: TestClient, account: str, path: str) -> list[dict[str, Any]]:
    response: httpx.Response = client.get(path, headers=tenant_headers(account))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_a_classifier_only_endpoint_is_listed_for_its_granted_account(byom: Harness) -> None:
    with started(byom, classifier_only_document(accounts=(ACCOUNT_A,))) as (client, upstream):
        granted = _rows(client, ACCOUNT_A, "/v1/providers")
        other = _rows(client, ACCOUNT_B, "/v1/providers")
        models = _rows(client, ACCOUNT_A, "/v1/models")

    assert [row for row in granted if row["id"] == ENDPOINT_A] == [
        {
            "object": "provider",
            "id": ENDPOINT_A,
            "display_name": "Lab endpoint aaaa",
            "auth_methods": ["api_key"],
        }
    ]
    assert ENDPOINT_A not in {row["id"] for row in other}
    # INVARIANT: listed as a provider, never as a chat model.
    assert ENDPOINT_A not in {row["id"].split("/", 1)[0] for row in models}
    assert upstream.calls == []


def test_every_other_provider_row_is_unchanged(byom: Harness) -> None:
    with byom.start(None) as client:
        before = _rows(client, ACCOUNT_A, "/v1/providers")
    with started(byom, classifier_only_document()) as (client, _upstream):
        after = _rows(client, ACCOUNT_A, "/v1/providers")

    assert [row for row in after if row["id"] != ENDPOINT_A] == before
