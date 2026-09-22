"""Classification before authority — the backfill's read-only half (OME-1208, S4).

# FEATURE: Stage B "Classification before authority": every `(account, provider)` pair is classified
# from the legacy index, the non-revoked Connections and the pair marker BEFORE anything changes its
# owner, and the classification decides a disposition the card's table names.
# INVARIANT (D3, D11): "proven the same" is a comparison of the decrypted credential documents in
# process — never a name or label; a pair that cannot be proven is quarantined or left alone, never
# guessed; revoked rows are never resurrected; classification writes NOTHING.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from backfill_probes import (
    CREDENTIAL_PROVIDER,
    classify,
    copy_profile_blob_to_connection,
    plan_tuple,
    revoke,
    seed_mapped_connection,
    seed_pending_connection,
    seed_profile_for,
    seed_quarantine,
    snapshot,
)
from connection_backed_admin_probes import KEY
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import PROVIDER

from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access.backfill_classify import BackfillContext, classify_account
from aigateway.plugins.anthropic_provider.auth import credential_service_for


@pytest.fixture
def h(authenticated_client: Any, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def profile_service(h: Any, name: str = "default") -> str:
    return credential_service_for(credential_name_for(h.account_id, name))


# --- Profile only ---------------------------------------------------------------------------------


def test_a_profile_only_pair_plans_a_connection_on_its_locator(h: Any) -> None:
    h.seed_document(credential="tok")
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "profile_only", "create")
    assert (plan.generation, plan.connection_id, plan.alias_documents) == (0, None, 0)
    assert plan.profile is not None and (plan.profile.name, plan.profile.auth_type) == (
        "default",
        "oauth",
    )


def test_a_profile_only_api_key_pair_plans_an_api_key_connection(h: Any) -> None:
    h.seed_document(auth_type="api_key", credential=KEY)
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "profile_only", "create")
    assert plan.profile is not None and plan.profile.auth_type == "api_key"


@pytest.mark.parametrize(
    ("state", "category"),
    [(ProfileState.PENDING, "profile_pending"), (ProfileState.ERROR, "profile_error")],
)
def test_a_pending_or_errored_profile_is_not_promoted(
    h: Any, state: ProfileState, category: str
) -> None:
    h.seed_document(state=state, credential="tok")
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", category, "skip")


def test_an_authenticated_profile_without_a_blob_is_not_promoted(h: Any) -> None:
    h.seed_document(credential=None)
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "profile_credential_missing", "skip")


def test_an_undecodable_profile_blob_is_not_promoted(h: Any) -> None:
    h.seed_document(credential=None)
    h.blobs.write_raw(profile_service(h), "default", "v1:!!!!:!!!!", ciphertext_version="v1")
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "profile_credential_undecodable", "skip")


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"a string"'])
def test_a_malformed_profile_blob_is_not_promoted(h: Any, raw: str) -> None:
    h.seed_document(credential=None)
    h.blobs.write(profile_service(h), "default", raw)
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "profile_credential_malformed", "skip")


def test_several_documents_stay_legacy(h: Any) -> None:
    h.seed_document(name="default", credential="tok")
    h.seed_document(name="work", credential="tok")
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "several_documents", "skip")


def test_a_provider_without_a_plugin_stays_legacy(h: Any) -> None:
    seed_profile_for(h, "nosuch", credential_provider="nosuch", credential="tok")
    assert plan_tuple(classify(h)["nosuch"]) == ("none", "provider_unknown", "skip")


# --- Connection only ------------------------------------------------------------------------------


def test_a_single_active_connection_is_named_effective(h: Any) -> None:
    connection_id = h.seed_connection(label="primary", credential="ctok")
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "connection_only", "name")
    assert (plan.connection_id, plan.generation, plan.profile) == (UUID(connection_id), 0, None)


def test_several_active_connections_stay_unmigrated(h: Any) -> None:
    h.seed_connection(label="one", credential="ctok")
    h.seed_connection(label="two", credential="ctok")
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "several_active_connections", "skip")


def test_connection_only_pairs_without_one_settled_active_row_stay_legacy(h: Any) -> None:
    seed_pending_connection(h, "pending-one")
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "connections_unsettled", "skip")
    h.seed_connection(label="primary", credential="ctok")
    # WHY: one active row beside a pending one is not "exactly one" — the pending flow may still
    # complete into a second active row, the policy the owner has not decided (D-S2b4-6).
    assert plan_tuple(classify(h)[PROVIDER]) == ("none", "connections_unsettled", "skip")


def test_a_revoked_connection_is_invisible_to_classification(h: Any) -> None:
    revoke(h, h.seed_connection(label="gone", credential="ctok"))
    assert PROVIDER not in classify(h)
    h.seed_document(credential="tok")
    # INVARIANT: revoked is never resurrected — the pair classifies as Profile only.
    assert plan_tuple(classify(h)[PROVIDER]) == ("migrated", "profile_only", "create")


# --- Profile and Connection -----------------------------------------------------------------------


def test_a_shadow_copy_of_the_same_credential_is_proven_same(h: Any) -> None:
    h.seed_document(credential="tok")
    connection_id = h.seed_connection(label="shadow", credential="anything")
    copy_profile_blob_to_connection(h, connection_id)
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "profile_connection_same", "name")
    assert plan.connection_id == UUID(connection_id)


def test_a_connection_already_on_the_profile_locator_is_mapped(h: Any) -> None:
    h.seed_document(credential="tok")
    connection_id = seed_mapped_connection(h)
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "profile_mapped", "name")
    assert plan.connection_id == UUID(connection_id)


def test_differing_credentials_are_quarantined_never_chosen(h: Any) -> None:
    h.seed_document(credential="tok")
    h.seed_connection(label="shadow", credential="other")
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("quarantined", "credentials_differ", "quarantine")
    assert plan.connection_id is None


def test_a_connection_whose_blob_is_missing_is_quarantined(h: Any) -> None:
    h.seed_document(credential="tok")
    h.seed_connection(label="shadow", credential=None)
    assert plan_tuple(classify(h)[PROVIDER]) == (
        "quarantined",
        "connection_credential_missing",
        "quarantine",
    )


def test_a_pending_connection_beside_a_profile_is_quarantined(h: Any) -> None:
    h.seed_document(credential="tok")
    seed_pending_connection(h)
    assert plan_tuple(classify(h)[PROVIDER]) == ("quarantined", "connection_pending", "quarantine")


def test_several_connections_beside_a_profile_are_quarantined(h: Any) -> None:
    h.seed_document(credential="tok")
    a = h.seed_connection(label="one", credential="x")
    h.seed_connection(label="two", credential="y")
    copy_profile_blob_to_connection(h, a)
    assert plan_tuple(classify(h)[PROVIDER]) == ("quarantined", "several_connections", "quarantine")


# --- the marker's say -----------------------------------------------------------------------------


def test_an_already_migrated_pair_is_left_alone(h: Any) -> None:
    h.seed_profile(credential="tok")
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "already_migrated", "skip")
    assert (str(plan.connection_id), plan.generation) == (h.migrated["default"], 1)


def test_a_migrated_pair_reports_its_alias_documents(h: Any) -> None:
    h.seed_profile(credential="tok")
    h.seed_document(name="work", credential=None)
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "already_migrated", "skip")
    # WHY: "work" addresses a blob the effective Connection does not — after an R1 rollback the
    # legacy path would read `credential_missing` for it, so the owner must see it before resetting.
    assert plan.alias_documents == 1


def test_a_quarantined_pair_that_became_clean_is_planned_from_its_generation(h: Any) -> None:
    h.seed_document(credential="tok")
    seed_quarantine(h)
    plan = classify(h)[PROVIDER]
    assert plan_tuple(plan) == ("migrated", "profile_only", "create")
    assert plan.generation == 1


def test_a_still_conflicting_quarantined_pair_plans_no_write(h: Any) -> None:
    h.seed_document(credential="tok")
    h.seed_connection(label="shadow", credential="other")
    seed_quarantine(h)
    assert plan_tuple(classify(h)[PROVIDER]) == ("quarantined", "credentials_differ", "skip")


# --- hygiene --------------------------------------------------------------------------------------


def test_classification_writes_nothing(h: Any) -> None:
    h.seed_document(credential="tok")
    h.seed_connection(label="shadow", credential="other")
    seed_profile_for(h, "nosuch", credential_provider="nosuch", credential="tok")
    before = snapshot(h)
    plans = classify(h)
    assert set(plans) == {PROVIDER, "nosuch"}
    assert snapshot(h) == before


def test_an_account_without_pairs_classifies_to_nothing(h: Any) -> None:
    assert classify(h) == {}
    assert CREDENTIAL_PROVIDER == "anthropic"


# --- the CLI's way in -----------------------------------------------------------------------------


def test_a_context_built_from_stores_classifies_like_the_app_context(h: Any) -> None:
    # WHY: the CLI has no app; it must reach the legacy index THROUGH this package (the A2 import
    # boundary makes `migrate_profiles.py` a consumer of the port, not an owner of the index).
    h.seed_document(credential="tok")
    app = h.client.app
    ctx = BackfillContext.from_stores(app.state.credential_store, app.state.providers)
    (plan,) = h.client.portal.call(classify_account, ctx, str(h.account_id))
    assert plan_tuple(plan) == ("migrated", "profile_only", "create")
    assert plan == classify(h)[PROVIDER]
