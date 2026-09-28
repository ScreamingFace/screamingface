"""Probes shared by the S4 backfill suites (OME-1208): seeding, snapshots, leak scans.

# AIDEV-NOTE: helpers only — each suite keeps its own fixtures explicit. Everything here reads the
# fixture database directly (sqlite) or goes through the real stores under the TestClient portal.
"""

from __future__ import annotations

import io
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from connection_backed_admin_probes import KEY
from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    credential_locator_for,
)
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.provider_access.backfill_apply import BackfillReport, run_backfill
from aigateway.core.provider_access.backfill_classify import (
    BackfillContext,
    PairPlan,
    classify_account,
)
from aigateway.core.provider_access.pair_authority import PairAuthorityStore
from aigateway.plugins.anthropic_provider.auth import credential_service_for

CREDENTIAL_PROVIDER = "anthropic"
SECRET_PROMPT = "TOP SECRET SYSTEM PROMPT"
# WHY: every string a leaking report/journal/log line could carry — scanned by `leaks_in`.
SECRET_NEEDLES = ("tok", "ctok", "other", KEY, SECRET_PROMPT, "v1:", "aigateway:", "default")


def context(harness: Any) -> BackfillContext:
    return BackfillContext.from_app(harness.client.app)


def classify(harness: Any, account_id: str | None = None) -> dict[str, PairPlan]:
    plans = harness.call(classify_account, context(harness), account_id or harness.account_id)
    return {plan.provider: plan for plan in plans}


def run(
    harness: Any,
    mode: str,
    *,
    account_ids: tuple[str, ...] | None = None,
    journal: io.StringIO | None = None,
) -> BackfillReport:
    return harness.call(
        run_backfill,
        context(harness),
        mode=mode,
        account_ids=account_ids or (harness.account_id,),
        journal=journal,
    )


def snapshot(harness: Any) -> tuple[list[Any], list[Any], list[Any]]:
    """Raw rows of the three tables a backfill may touch — byte-for-byte."""
    with sqlite3.connect(harness.blobs.db_path) as conn:
        return (
            conn.execute("select * from credential_blobs order by service, account").fetchall(),
            conn.execute("select * from oauth_connections order by id").fetchall(),
            conn.execute("select * from provider_credential_slots order by id").fetchall(),
        )


def leaks_in(text: str, *, allow: tuple[str, ...] = ()) -> list[str]:
    return [needle for needle in SECRET_NEEDLES if needle not in allow and needle in text]


def credential_provider_of(harness: Any, provider: str) -> str:
    plugin = harness.client.app.state.providers.get(provider)
    return credential_service_provider_for(plugin, provider)


def seed_profile_for(
    harness: Any,
    provider: str,
    *,
    credential_provider: str,
    credential: str | None = "tok",
    name: str = "default",
    auth_type: AuthType = "oauth",
    state: ProfileState = ProfileState.AUTHENTICATED,
    account_id: str | None = None,
) -> Profile:
    """A legacy document (+ blob) for ANY provider/account — the base harness pins anthropic."""
    owner: str = account_id if account_id is not None else str(harness.account_id)
    if credential is not None:
        value = (
            json.dumps({"access_token": credential, "refresh_token": "rt", "token_type": "Bearer"})
            if auth_type == "oauth"
            else json.dumps({"auth_type": "api_key", "api_key": credential})
        )
        locator = credential_locator_for(credential_provider, owner, name)
        harness.blobs.write(locator["service"], locator["account"], value)
    profile = Profile(
        id=profile_id_for(owner, provider, name),
        account_id=owner,
        provider=provider,
        name=name,
        state=state,
        auth_type=auth_type,
        defaults=ProfileDefaults(system_prompt=SECRET_PROMPT),
    )
    harness.call(ProfileIndexStore(credential_store=harness.blobs.store).upsert, profile)
    return profile


def copy_profile_blob_to_connection(
    harness: Any, connection_id: str, name: str = "default"
) -> None:
    """Make the Connection's blob the SAME credential document as the Profile's (a shadow copy)."""
    value = harness.blobs.read(
        credential_service_for(credential_name_for(harness.account_id, name)), "default"
    )
    assert value is not None
    harness.blobs.write(
        credential_service_for(credential_key_for(harness.account_id, connection_id)),
        "default",
        value,
    )


def seed_pending_connection(harness: Any, label: str = "pending-one") -> str:
    connection = harness.call(
        OAuthConnectionStore().create_pending,
        account_id=harness.account_id,
        provider=PROVIDER,
        label=label,
        connection_id=uuid4(),
    )
    return str(connection.id)


def seed_mapped_connection(
    harness: Any, name: str = "default", *, auth_type: AuthType = "oauth"
) -> str:
    """An ACTIVE row whose locator IS the Profile address (what S2'b2's fresh flow leaves)."""

    async def create() -> Any:
        store = OAuthConnectionStore()
        pending = await store.create_pending(
            account_id=harness.account_id,
            provider=PROVIDER,
            label=name,
            connection_id=uuid4(),
            credential_provider=CREDENTIAL_PROVIDER,
            credential_locator=credential_locator_for(
                CREDENTIAL_PROVIDER, harness.account_id, name
            ),
        )
        if auth_type != "oauth":
            pending = await store.set_auth_type(pending, auth_type) or pending
        return await store.complete(pending, label=name, identity=None)

    return str(harness.call(create).id)


def revoke(harness: Any, connection_id: str) -> None:
    async def do() -> None:
        store = OAuthConnectionStore()
        row = await store.get(harness.account_id, connection_id)
        assert row is not None
        await store.mark_revoked(row)

    harness.call(do)


def seed_quarantine(harness: Any, note: str = "credentials_differ") -> Any:
    return harness.call(
        PairAuthorityStore().advance,
        harness.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note=note,
    )


def plan_tuple(plan: PairPlan) -> tuple[str, str, str]:
    return (plan.disposition, plan.category, plan.action)


def token_of(harness: Any, connection_id: str | UUID) -> Any:
    return harness.client.get(f"/v1/oauth/connections/{connection_id}/token")


__all__ = [
    "CREDENTIAL_PROVIDER",
    "SECRET_NEEDLES",
    "SECRET_PROMPT",
    "classify",
    "context",
    "copy_profile_blob_to_connection",
    "credential_provider_of",
    "leaks_in",
    "plan_tuple",
    "revoke",
    "run",
    "seed_mapped_connection",
    "seed_pending_connection",
    "seed_profile_for",
    "seed_quarantine",
    "snapshot",
    "token_of",
]
