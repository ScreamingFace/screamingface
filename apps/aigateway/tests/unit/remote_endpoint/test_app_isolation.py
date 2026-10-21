"""Two endpoints, two accounts, the real admin key lifecycle: every pair stays its own.

# FEATURE: hosted BYOM Unit 0 — exit evidence. The tests tell `(A, endpoint A)`, `(A, endpoint B)`
# and `(B, endpoint A)` apart by the exact URL and bearer the fake upstream receives, sequentially,
# under overlapping requests and probes, and across key replacement and deletion.
# STORY: as an operator, I attach, replace and remove tenants' keys for approved endpoints; a
# mistake or a removal for one tenant/endpoint never changes what another pair sends.
# INVARIANT: both endpoints use the same upstream model name, so only the provider instance and
# its stored key can route a request.
"""

from __future__ import annotations

import asyncio

import httpx

from .conftest import (
    MALFORMED,
    PEER,
    REJECTED,
    WRONG_TYPE,
    Harness,
    admin_headers,
    chat,
    chat_body,
    delete_pair,
    echo_of,
    put_key,
    tenant_headers,
)
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

KEY = {
    (ACCOUNT_A, ENDPOINT_A): "sk-alice-on-a-0001",
    (ACCOUNT_A, ENDPOINT_B): "sk-alice-on-b-0001",
    (ACCOUNT_B, ENDPOINT_A): "sk-bob-on-a-0001",
}
URL = {ENDPOINT_A: ORIGIN_A + CHAT_PATH, ENDPOINT_B: ORIGIN_B + CHAT_PATH}


def _echo(provider: str, key: str) -> str:
    return f"{URL[provider]}|Bearer {key}"


def _attach_all(client, byom: Harness) -> None:
    for (account, provider), key in KEY.items():
        response = put_key(client, account, provider, key)
        assert response.status_code == 200, response.text
    byom.upstream.calls.clear()


def test_admin_attach_probes_each_pair_and_stores_its_key_under_the_instance(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        responses = [put_key(client, a, p, key) for (a, p), key in KEY.items()]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert [r.json()["provider"] for r in responses] == [p for (_, p) in KEY]
    assert not any(key in r.text for r, key in zip(responses, KEY.values(), strict=True))
    assert [(c.url, c.bearer, c.model, c.probe) for c in byom.upstream.calls] == [
        (URL[p], f"Bearer {key}", UPSTREAM_MODEL, True) for (_, p), key in KEY.items()
    ]
    for (account, provider), key in KEY.items():
        assert byom.stored_key(account, provider) == key
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_B) is None


def test_each_pairs_chat_reaches_only_its_endpoint_with_its_key(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        echoes = {pair: echo_of(chat(client, *pair)) for pair in KEY}

    assert echoes == {(a, p): _echo(p, key) for (a, p), key in KEY.items()}
    assert [(c.url, c.bearer, c.model, c.probe) for c in byom.upstream.calls] == [
        (URL[p], f"Bearer {key}", UPSTREAM_MODEL, False) for (_, p), key in KEY.items()
    ]


def test_overlapping_chats_and_probes_never_cross_and_a_failed_replacement_keeps_the_key(
    byom: Harness,
) -> None:
    probe_key = "sk-alice-probe-on-b-0001"
    bad_key = f"sk-{REJECTED}-alice-on-a-0002"
    chats = [pair for pair in KEY for _ in range(2)]

    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        # Six chats, one standalone probe and one failing replacement probe: all eight requests
        # must be in flight at the same moment, or the fake upstream's barrier times out.
        byom.upstream.expect_overlap(len(chats) + 2)

        async def overlap() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=client.app, client=PEER)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                requests = [
                    http.post("/v1/chat/completions", json=chat_body(p), headers=tenant_headers(a))
                    for a, p in chats
                ]
                requests.append(
                    http.post(
                        "/v1/oauth/connections/api-key/validate",
                        json={"provider": ENDPOINT_B, "api_key": probe_key},
                        headers=tenant_headers(ACCOUNT_A),
                    )
                )
                requests.append(
                    http.put(
                        f"/v1/admin/accounts/{ACCOUNT_A}/connections/{ENDPOINT_A}/api-key",
                        json={"api_key": bad_key},
                        headers=admin_headers(),
                    )
                )
                return list(await asyncio.gather(*requests))

        assert client.portal is not None
        responses = client.portal.call(overlap)
        byom.upstream.expect_overlap(0)
        after = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))

    *chat_responses, probe, replacement = responses
    assert [echo_of(r) for r in chat_responses] == [_echo(p, KEY[(a, p)]) for a, p in chats]
    assert probe.status_code == 200 and probe.json()["state"] == "valid"
    assert replacement.status_code == 422
    assert replacement.json()["detail"]["code"] == "api_key_invalid"
    assert bad_key not in replacement.text
    # INVARIANT: the refused replacement wrote nothing; the old key still serves the pair.
    assert after == _echo(ENDPOINT_A, KEY[(ACCOUNT_A, ENDPOINT_A)])
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY[(ACCOUNT_A, ENDPOINT_A)]
    probes = sorted((c.url, c.bearer) for c in byom.upstream.calls if c.probe)
    assert probes == sorted(
        [(URL[ENDPOINT_B], f"Bearer {probe_key}"), (URL[ENDPOINT_A], f"Bearer {bad_key}")]
    )
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_B) == KEY[(ACCOUNT_A, ENDPOINT_B)]


def test_a_successful_replacement_moves_only_that_pair(byom: Harness) -> None:
    new_key = "sk-alice-on-a-0002"

    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        before = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, new_key).status_code == 200
        echoes = {pair: echo_of(chat(client, *pair)) for pair in KEY}

    assert before == _echo(ENDPOINT_A, KEY[(ACCOUNT_A, ENDPOINT_A)])
    # WHY the cached strategy cannot go stale: it reads the store on every authorization.
    assert echoes[(ACCOUNT_A, ENDPOINT_A)] == _echo(ENDPOINT_A, new_key)
    assert echoes[(ACCOUNT_B, ENDPOINT_A)] == _echo(ENDPOINT_A, KEY[(ACCOUNT_B, ENDPOINT_A)])
    assert echoes[(ACCOUNT_A, ENDPOINT_B)] == _echo(ENDPOINT_B, KEY[(ACCOUNT_A, ENDPOINT_B)])


def test_deleting_one_pair_leaves_the_other_pairs_working(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        deleted = delete_pair(client, ACCOUNT_A, ENDPOINT_A)
        refused = chat(client, ACCOUNT_A, ENDPOINT_A)
        refused_calls = list(byom.upstream.calls)
        survivors = {
            pair: echo_of(chat(client, *pair)) for pair in KEY if pair != (ACCOUNT_A, ENDPOINT_A)
        }

    assert deleted.status_code == 204
    assert refused.status_code in (404, 409), refused.text
    assert refused_calls == []
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) is None
    assert survivors == {
        (ACCOUNT_A, ENDPOINT_B): _echo(ENDPOINT_B, KEY[(ACCOUNT_A, ENDPOINT_B)]),
        (ACCOUNT_B, ENDPOINT_A): _echo(ENDPOINT_A, KEY[(ACCOUNT_B, ENDPOINT_A)]),
    }
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_A) == KEY[(ACCOUNT_B, ENDPOINT_A)]


def test_a_replacement_answered_by_a_malformed_completion_keeps_the_old_key(
    byom: Harness,
) -> None:
    # STORY: as an operator, I replace a tenant's key while the endpoint answers HTTP 200 with a
    # body that is not a completion; the new key is not published and the tenant keeps working.
    malformed_key = f"sk-{MALFORMED}-alice-on-a-0003"

    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        replacement = put_key(client, ACCOUNT_A, ENDPOINT_A, malformed_key)
        after = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))

    assert replacement.status_code == 503, replacement.text
    assert replacement.json()["detail"]["code"] == "api_key_validation_unavailable"
    assert malformed_key not in replacement.text
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY[(ACCOUNT_A, ENDPOINT_A)]
    assert after == _echo(ENDPOINT_A, KEY[(ACCOUNT_A, ENDPOINT_A)])
    probes = [c for c in byom.upstream.calls if c.probe]
    assert [(c.url, c.bearer) for c in probes] == [(URL[ENDPOINT_A], f"Bearer {malformed_key}")]


def test_a_replacement_answered_with_the_wrong_content_type_keeps_the_old_key(
    byom: Harness,
) -> None:
    # STORY: as an operator, I replace a tenant's key while the endpoint answers a well-formed
    # completion as `text/html`; chat would refuse that answer, so the key is not published.
    wrong_type_key = f"sk-{WRONG_TYPE}-alice-on-a-0004"

    with byom.start(two_endpoint_document()) as client:
        _attach_all(client, byom)
        replacement = put_key(client, ACCOUNT_A, ENDPOINT_A, wrong_type_key)
        after = echo_of(chat(client, ACCOUNT_A, ENDPOINT_A))

    assert replacement.status_code == 503, replacement.text
    assert replacement.json()["detail"]["code"] == "api_key_validation_unavailable"
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY[(ACCOUNT_A, ENDPOINT_A)]
    assert after == _echo(ENDPOINT_A, KEY[(ACCOUNT_A, ENDPOINT_A)])
