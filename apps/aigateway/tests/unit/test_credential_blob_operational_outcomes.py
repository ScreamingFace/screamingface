from __future__ import annotations

SERVICE = "aigateway:openrouter:test-key"
ACCOUNT = "default"


def _store(client):
    return client.app.state.credential_store


def test_credential_write_resets_the_operational_register(client) -> None:
    store = _store(client)
    client.portal.call(store.write, SERVICE, ACCOUNT, "first")
    observation = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert observation is not None
    assert client.portal.call(store.record_dispatch_outcome, observation, "insufficient_credits")

    before = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert before is not None
    assert before.outcome == "insufficient_credits"

    client.portal.call(store.write, SERVICE, ACCOUNT, "replacement")
    after = client.portal.call(store.operational_state, SERVICE, ACCOUNT)

    assert after is not None
    assert after.blob_id == before.blob_id
    assert after.credential_revision == before.credential_revision + 1
    assert after.next_dispatch_sequence == 0
    assert after.last_outcome_sequence == 0
    assert after.outcome is None


def test_newer_admitted_outcome_wins_when_completions_are_reversed(client) -> None:
    store = _store(client)
    client.portal.call(store.write, SERVICE, ACCOUNT, "key")
    older = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    newer = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert older is not None and newer is not None

    assert client.portal.call(store.record_dispatch_outcome, newer, "connected")
    assert not client.portal.call(store.record_dispatch_outcome, older, "insufficient_credits")

    state = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert state is not None
    assert state.last_outcome_sequence == newer.dispatch_sequence
    assert state.outcome == "connected"


def test_replacement_fences_an_old_dispatch_completion(client) -> None:
    store = _store(client)
    client.portal.call(store.write, SERVICE, ACCOUNT, "old")
    stale = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert stale is not None

    client.portal.call(store.write, SERVICE, ACCOUNT, "new")

    assert not client.portal.call(store.record_dispatch_outcome, stale, "needs_reauth")
    state = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert state is not None
    assert state.credential_revision > stale.credential_revision
    assert state.outcome is None


def test_dispatch_admission_returns_none_for_an_absent_blob(client) -> None:
    assert client.portal.call(_store(client).begin_dispatch, SERVICE, ACCOUNT) is None


def test_credential_blob_probe_replacement_mirrors_the_runtime_store(
    client, credential_blobs
) -> None:
    credential_blobs.write(SERVICE, ACCOUNT, "first")
    store = _store(client)
    observation = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert observation is not None
    assert client.portal.call(store.record_dispatch_outcome, observation, "insufficient_credits")
    before = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert before is not None

    credential_blobs.write(SERVICE, ACCOUNT, "replacement")
    after = client.portal.call(store.operational_state, SERVICE, ACCOUNT)

    assert after is not None
    assert after.credential_revision == before.credential_revision + 1
    assert after.next_dispatch_sequence == 0
    assert after.last_outcome_sequence == 0
    assert after.outcome is None


def test_credential_mutation_resets_the_operational_register(client) -> None:
    store = _store(client)
    client.portal.call(store.write, SERVICE, ACCOUNT, "first")
    observation = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert observation is not None
    assert client.portal.call(store.record_dispatch_outcome, observation, "needs_reauth")
    before = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert before is not None

    client.portal.call(store.mutate, SERVICE, ACCOUNT, lambda value: f"{value}-rotated")
    after = client.portal.call(store.operational_state, SERVICE, ACCOUNT)

    assert client.portal.call(store.read, SERVICE, ACCOUNT) == "first-rotated"
    assert after is not None
    assert after.credential_revision == before.credential_revision + 1
    assert after.next_dispatch_sequence == 0
    assert after.last_outcome_sequence == 0
    assert after.outcome is None


def test_an_observation_cannot_replace_itself(client) -> None:
    store = _store(client)
    client.portal.call(store.write, SERVICE, ACCOUNT, "key")
    observation = client.portal.call(store.begin_dispatch, SERVICE, ACCOUNT)
    assert observation is not None

    assert client.portal.call(store.record_dispatch_outcome, observation, "connected")
    assert not client.portal.call(
        store.record_dispatch_outcome, observation, "insufficient_credits"
    )

    state = client.portal.call(store.operational_state, SERVICE, ACCOUNT)
    assert state is not None
    assert state.last_outcome_sequence == observation.dispatch_sequence
    assert state.outcome == "connected"
