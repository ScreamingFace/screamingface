"""The caller's classifier catalog: `GET /v1/classifiers` and `GET /v1/classifiers/details`.

# FEATURE: hosted BYOM Unit 3 — a granted account lists its classifiers and reads, for one, what it
# is asked, how it answers and whether that account's own Connection can run it.
# INVARIANT: the VIEW grant gates both routes, as for `/v1/model-parameters`; every answer, success
# or refusal, is `private, no-store` and varies by authorization.
# INVARIANT: an ungranted caller gets the unknown-provider answer whatever the alias, so it cannot
# learn which aliases exist; a granted caller's unknown or chat alias is `404 model_not_found`.
# INVARIANT: no catalog answer names an origin or a request path, and none reaches the upstream.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from .classifier_upstream import classifier_id, classifier_only_document, mixed_document, started
from .conftest import Harness, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CLASSIFIER_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
)

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Authorization"}
UNREGISTERED = "byom_" + "c" * 32


def _list(client: TestClient, account: str) -> httpx.Response:
    return client.get("/v1/classifiers", headers=tenant_headers(account))


def _details(client: TestClient, account: str, model: str) -> httpx.Response:
    return client.get(
        "/v1/classifiers/details", params={"model": model}, headers=tenant_headers(account)
    )


def _ids(response: httpx.Response) -> set[str]:
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["data"]}


def _assert_private(*responses: httpx.Response) -> None:
    for response in responses:
        assert {key: response.headers.get(key) for key in PRIVATE} == PRIVATE
        assert ORIGIN_A not in response.text and ORIGIN_B not in response.text
        assert CLASSIFIER_PATH not in response.text


def test_each_account_lists_exactly_the_classifiers_granted_to_it(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, upstream):
        seen_a, seen_b = _list(client, ACCOUNT_A), _list(client, ACCOUNT_B)

    assert _ids(seen_a) == {classifier_id(ENDPOINT_A), classifier_id(ENDPOINT_B)}
    assert _ids(seen_b) == {classifier_id(ENDPOINT_A)}
    row = next(r for r in seen_a.json()["data"] if r["id"] == classifier_id(ENDPOINT_A))
    assert row == {
        "object": "classifier",
        "id": classifier_id(ENDPOINT_A),
        "owned_by": ENDPOINT_A,
        "task": "text-classification",
        "contract": "hf-text-classification-v1",
    }
    # INVARIANT: chat models stay in `/v1/models`; none is listed here.
    assert not {f"{ENDPOINT_A}/{ALIAS}", f"{ENDPOINT_B}/{ALIAS}"} & _ids(seen_a)
    _assert_private(seen_a, seen_b)
    assert upstream.calls == []


def test_an_ungranted_account_and_a_disabled_endpoint_list_nothing(byom: Harness) -> None:
    with started(byom, classifier_only_document(accounts=(ACCOUNT_A,))) as (client, _upstream):
        ungranted = _list(client, ACCOUNT_B)
    with started(byom, mixed_document(b_enabled=False)) as (client, _upstream):
        disabled = _list(client, ACCOUNT_A)

    assert _ids(ungranted) == set()
    assert _ids(disabled) == {classifier_id(ENDPOINT_A)}


def test_the_details_read_missing_until_that_account_attaches_a_key(byom: Harness) -> None:
    model = classifier_id(ENDPOINT_A)
    with started(byom, mixed_document()) as (client, upstream):
        before = _details(client, ACCOUNT_A, model)
        assert (
            put_key(client, ACCOUNT_A, ENDPOINT_A, "sk-alice-on-a-catalog-0001").status_code == 200
        )
        upstream.calls.clear()
        byom.upstream.calls.clear()
        after = _details(client, ACCOUNT_A, model)
        other = _details(client, ACCOUNT_B, model)

    assert [r.status_code for r in (before, after, other)] == [200, 200, 200], before.text
    assert before.json() == {
        "object": "classifier",
        "id": model,
        "owned_by": ENDPOINT_A,
        "task": "text-classification",
        "contract": "hf-text-classification-v1",
        "result_contract": "classification-scores-v1",
        "execution_access": "missing",
    }
    assert after.json()["execution_access"] == "configured"
    # INVARIANT: a Connection is per (account, endpoint) pair; A's key configures no one else.
    assert other.json()["execution_access"] == "missing"
    _assert_private(before, after, other)
    assert (upstream.calls, byom.upstream.calls) == ([], [])


@pytest.mark.parametrize("alias", ["classifier_v1", "undeclared_v1", ALIAS])
def test_an_ungranted_caller_gets_the_unknown_provider_answer_whatever_the_alias(
    byom: Harness, alias: str
) -> None:
    with started(byom, mixed_document()) as (client, _upstream):
        denied = _details(client, ACCOUNT_B, f"{ENDPOINT_B}/{alias}")
        absent = _details(client, ACCOUNT_B, f"{UNREGISTERED}/{alias}")

    assert denied.status_code == 400, denied.text
    assert denied.json() == {"detail": f"unknown provider: {ENDPOINT_B}"}
    assert (denied.status_code, denied.text.replace(ENDPOINT_B, UNREGISTERED)) == (
        absent.status_code,
        absent.text,
    )
    _assert_private(denied, absent)


@pytest.mark.parametrize("alias", ["undeclared_v1", ALIAS], ids=["unknown", "chat"])
def test_a_granted_caller_s_unknown_or_chat_alias_is_not_found(byom: Harness, alias: str) -> None:
    model = f"{ENDPOINT_A}/{alias}"
    with started(byom, mixed_document()) as (client, _upstream):
        response = _details(client, ACCOUNT_A, model)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "model_not_found",
        "provider": ENDPOINT_A,
        "model": model,
    }
    _assert_private(response)


def test_a_model_without_a_provider_prefix_is_refused_privately(byom: Harness) -> None:
    with started(byom, mixed_document()) as (client, _upstream):
        response = _details(client, ACCOUNT_A, "classifier_v1")

    assert response.status_code == 400, response.text
    _assert_private(response)
