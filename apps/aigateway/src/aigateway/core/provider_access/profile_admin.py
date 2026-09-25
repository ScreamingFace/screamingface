"""The Profile-backed `ProviderCredentialAdmin` (OME-1230, Stage A3 of OME-1138; spec §3.3 ops 7–9).

Relocated from `routes/auth.py` at 248b0b6d — `upsert_api_key_profile` (:1251-1359) and
`delete_profile_for_account` (:1370-1402) — together with the listing bodies of the tenant and
admin Profile routes. Behaviour unchanged; those routes are now shells over this module.

# FEATURE: OME-1138 — the credential write bodies sit behind ONE interface so Stage B (D11) can
# swap the backing without touching a route.
# INVARIANT (OME-307, relocated intact): index-row CAS FIRST, credential blob SECOND, ONE
# transaction, delete-wins; transaction rollback is the SOLE atomicity mechanism.
# INVARIANT (hexagonal): nothing here names an HTTP status or imports a route. Refusals are typed
# and the edge table in `routes/provider_access_http.py` renders them.
# COMPATIBILITY (window-only, removed at Stage E / OME-1209 with the shells): `legacy_name` and
# `CredentialSummary.legacy_projection` exist so the shells keep today's JSON byte-identical.
# Op 8 lost its `defaults` keyword at the D2 cutover (OME-1323): no writer stores defaults.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from tortoise.transactions import in_transaction

from ..credential_blob.store import CredentialBlobMutationConflict
from ..credential_strategy_cache import credential_strategy_cache
from ..plugin_base import credential_strategy_from
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict
from ..profile_models import AuthType, Profile, ProfileState, credential_name_for, profile_id_for
from .ports import ProviderCredentialAdmin
from .profile_authorize import invalidate_session
from .types import (
    CredentialStoreUnavailable,
    CredentialSummary,
    ProviderUnknown,
    TargetMissing,
    UnsupportedAuthMode,
    WriteConflict,
)

logger = logging.getLogger(__name__)

# WHY a constant: spec op 8 — `legacy_name or "default"` names the Profile in the window.
DEFAULT_LEGACY_NAME = "default"


def summary_of(profile: Profile) -> CredentialSummary:
    """The masked admin-facing view of one legacy Profile, plus its window-only projection."""
    return CredentialSummary(
        provider=profile.provider,
        selector=profile.name,
        auth_type=profile.auth_type,
        state=profile.state.value,
        legacy_projection=profile.model_dump(mode="json"),
    )


async def persist_credentials_or_refuse(
    strategy: Any, credentials: dict[str, Any], *, description: str
) -> None:
    """Persist through the strategy or refuse with the typed store-unavailable outcome.

    Today's `routes/credential_persistence.py::persist_credentials_or_503` minus the HTTP; the
    OAuth flows keep using that helper, this one serves the admin boundary.
    # AIDEV-NOTE: this module-level seam is what the OME-307 rollback race test
    # (`test_set_api_key_rollback_does_not_compensate_over_same_key_external_commit`) patches to
    # fail S1 AFTER its transactional write — re-expressed here from the route module at A3 (F2).
    # Call it through the module attribute, never by a captured reference, or the seam is dead.
    """
    try:
        await strategy.persist_credentials(credentials)
    except Exception as exc:
        # WHY `Exception`: the store adapter is a port; any failure it raises means "not stored".
        # Store adapters may echo credentials in exception text; log only type + service.
        logger.error(
            "Failed to persist %s for service %s: %s",
            description,
            strategy.credential_service(),
            type(exc).__name__,
        )
        raise CredentialStoreUnavailable(description) from exc


class ProfileBackedCredentialAdmin:
    """The compatibility-window implementation: legacy Profile rows plus credential blobs."""

    def __init__(self, app: Any) -> None:
        # WHY the app, not the stores: `profile_index`, `providers`, `credential_store` and
        # `{provider}_http_factory` are read LAZILY at call time, exactly as the route bodies did —
        # tests monkeypatch them onto `app.state` after the app is built.
        self._app = app

    @property
    def _index(self) -> ProfileIndexStore:
        return self._app.state.profile_index

    def _plugin(self, provider: str) -> Any:
        plugin = self._app.state.providers.get(provider)
        if plugin is None:
            raise ProviderUnknown(provider)
        return plugin

    def _strategy(
        self, plugin: Any, provider: str, credential_name: str, *, auth_type: AuthType
    ) -> Any:
        # WHY not the shared cache: the write path builds a fresh strategy exactly as the route
        # did; the cache is EVICTED after the commit so readers never serve a stale token.
        return credential_strategy_from(
            plugin,
            credential_name,
            auth_type=auth_type,
            credential_store=self._app.state.credential_store,
            http_client_factory=getattr(self._app.state, f"{provider}_http_factory", None),
        )

    def _invalidate(self, plugin: Any, credential_name: str) -> None:
        # Cache invalidation follows the durable boundary so it reflects the committed write.
        invalidate_session(plugin, credential_name)
        # Drop the shared cached strategy so re-auth / api-key change / delete never serve a stale
        # in-memory token from a prior credential (SF-282).
        credential_strategy_cache(self._app).evict(credential_name)

    async def list(
        self, account_id: str, provider: str | None = None
    ) -> tuple[CredentialSummary, ...]:
        """Op 7 — masked summaries of the account's legacy Profiles; never a secret."""
        return tuple(summary_of(p) for p in await self._index.list(account_id, provider))

    async def set_api_key(
        self,
        account_id: str,
        provider: str,
        *,
        raw_api_key: str,
        legacy_name: str | None,
    ) -> CredentialSummary:
        """Op 8 — publish an API key as an AUTHENTICATED legacy Profile plus its credential blob.

        No OAuth round-trip: the Profile is AUTHENTICATED as soon as the key is stored. The key is
        persisted to the Profile's credential slot (so a later OAuth completion overwrites it, and
        delete removes it). The RAW key never appears in a summary, projection or log; the Profile
        carries only the masked last-4 label (``"API key ····WXYZ"``), the Stripe/AWS/GitHub
        convention. `raw_api_key` arrives normalised (stripped, length-checked) by the shell.
        """
        name = legacy_name or DEFAULT_LEGACY_NAME
        plugin = self._plugin(provider)
        credential_name = credential_name_for(account_id, name)
        strategy = self._strategy(plugin, provider, credential_name, auth_type="api_key")
        if strategy is None:
            raise UnsupportedAuthMode("api_key", provider=provider)

        profile = await self._index.get(account_id, provider, name)
        # INVARIANT (OME-307 Unit 3): if we observed an existing profile, publication must not
        # resurrect it should a concurrent delete remove it before we commit (delete wins).
        profile_observed = profile is not None
        if profile is None:
            profile = Profile(
                id=profile_id_for(account_id, provider, name),
                account_id=account_id,
                provider=provider,
                name=name,
            )
        # INVARIANT (OME-1323, D2): `profile.defaults` is never written here — an existing
        # Profile keeps its historical defaults byte-identical, and a new one gets the empty
        # model default.
        profile.auth_type = "api_key"
        profile.state = ProfileState.AUTHENTICATED
        profile.last_refreshed_at = datetime.now(UTC)
        profile.account_label = f"API key ····{raw_api_key[-4:]}"
        profile.scopes = []  # OAuth scopes are meaningless for API-key auth (F24)

        # WHY: the credential blob and profile index share the Tortoise connection; publish both
        # in one short transaction so readers never observe a committed mixed auth type.
        # INVARIANT (OME-307 Blocker 3): the index-row CAS runs FIRST, the credential write
        # SECOND — ONE consistent lock order shared with `delete`. The account index row is the
        # sole ALWAYS-PRESENT row, so it is the only row that serializes a concurrent delete; the
        # credential row may be absent, and a missing-row operation takes no lock under READ
        # COMMITTED. Publishing the index first means a racing delete that removed the profile
        # makes require_present raise BEFORE any credential is written, so nothing is orphaned or
        # resurrected.
        # INVARIANT (OME-307 Blocker 4): transaction rollback is the SOLE atomicity mechanism.
        # ORMStore writes through the transaction's connection, so a failed OR cancelled
        # publication (including a 3.12 CancelledError, a BaseException) rolls back BOTH the index
        # upsert and the credential write. There is deliberately NO out-of-transaction
        # compensation: a second, post-rollback credential mutate is redundant with rollback AND
        # could race a concurrent writer that legitimately owns the slot (an ABA clobber). Any
        # exception other than the two typed conflicts propagates unchanged so the enclosing txn
        # rolls back and re-raises.
        try:
            async with in_transaction():
                # INVARIANT (OME-307 Unit 3): an observed-existing profile publishes conditionally
                # so a concurrent delete WINS (no resurrection); a first-time key stays an
                # unconditional create. Splitting the call keeps `upsert(profile)` — the create
                # contract — untouched for the common path.
                if profile_observed:
                    await self._index.upsert(profile, require_present=True)
                else:
                    await self._index.upsert(profile)
                await persist_credentials_or_refuse(
                    strategy,
                    {"auth_type": "api_key", "api_key": raw_api_key},
                    description="API-key credentials",
                )
        except ProfileTransitionConflict as exc:
            # A concurrent delete removed the profile we were updating: delete wins, so the
            # rolled-back publication surfaces as the superseded conflict (409 at the edge).
            raise WriteConflict(
                "superseded", subject="profile", provider=provider, requested=name
            ) from exc
        except CredentialBlobMutationConflict as exc:
            # The index-row CAS ran out of retries (503 `profile_index_conflict` at the edge).
            raise WriteConflict(
                "retry_exhausted", subject="profile", provider=provider, requested=name
            ) from exc
        self._invalidate(plugin, credential_name)
        return summary_of(profile)

    async def delete(self, account_id: str, provider: str, *, legacy_name: str) -> None:
        """Op 9 — remove one legacy Profile and its credential."""
        plugin = self._plugin(provider)
        profile = await self._index.get(account_id, provider, legacy_name)
        if profile is None:
            raise TargetMissing(provider, legacy_name)
        credential_name = credential_name_for(account_id, legacy_name)
        strategy = self._strategy(plugin, provider, credential_name, auth_type=profile.auth_type)
        # INVARIANT (OME-307 Unit 3 + Blocker 3): publish the profile-index removal and the
        # credential deletion in ONE transaction so a committed delete never leaves an orphan
        # credential (a blob with no profile). The index-row CAS runs FIRST: it is the sole
        # ALWAYS-PRESENT row, so it is the only row that serializes a concurrent api-key set. The
        # credential row may be ABSENT (e.g. a pending/errored OAuth profile), and a missing-row
        # DELETE takes NO lock under READ COMMITTED — so serializing on it would let a racing set
        # slip an INSERT past this delete and orphan a credential. Rollback keeps blob + index
        # coherent on any failure.
        async with in_transaction():
            await self._index.remove(profile.id)
            if strategy is not None:
                await strategy.delete_credentials()
        self._invalidate(plugin, credential_name)


def provider_credential_admin_for(app: Any) -> ProviderCredentialAdmin:
    """The app's admin interface; created Profile-backed only when none is wired.

    # INVARIANT (mirrors `provider_access_for`): whatever `app.state.provider_credential_admin`
    # holds IS the interface — a fake in a test or a later backing must be what the shells call.
    # The lazy branch exists for apps built without `main.create_app` and only fills an ABSENT slot.
    """
    admin = getattr(app.state, "provider_credential_admin", None)
    if admin is None:
        admin = ProfileBackedCredentialAdmin(app)
        app.state.provider_credential_admin = admin
    return admin
