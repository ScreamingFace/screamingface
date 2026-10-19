"""Shared helpers of the D18 credential publication (OME-1230 A3; reshaped by OME-1209 E3b).

What is left of the Profile-backed admin after E3 retired the Profile routes and E3b deleted their
ops 7-9: the default compat-document name, the typed persist, the shared-address guard, and the
base class whose strategy and cache helpers `ConnectionBackedCredentialAdmin` builds on.

# FEATURE: OME-1138 D18 — `pair_admin_writes` publishes an admin's API key through
# `ConnectionBackedCredentialAdmin.publish_api_key`, which writes a compat-document mirror.
# INVARIANT (hexagonal): nothing here names an HTTP status or imports a route. Refusals are typed
# and the edge table in `routes/provider_access_http.py` renders them.
"""

from __future__ import annotations

import logging
from typing import Any

from ..auth_types import AuthType
from ..credential_strategy_cache import credential_strategy_cache
from ..oauth.models import OAuthConnection
from ..oauth.store import credential_locator_for
from ..plugin_base import credential_service_provider_for, credential_strategy_from
from ..profile_index import ProfileIndexStore
from .profile_authorize import invalidate_session
from .types import CredentialStoreUnavailable

logger = logging.getLogger(__name__)

# WHY a constant: the D18 PUT's compat-document name when the pair has no document yet.
DEFAULT_LEGACY_NAME = "default"


async def persist_credentials_or_refuse(
    strategy: Any, credentials: dict[str, Any], *, description: str
) -> None:
    """Persist through the strategy or refuse with the typed store-unavailable outcome.

    `routes/credential_persistence.py::persist_credentials_or_503` minus the HTTP; the OAuth
    flows keep using that helper, this one serves the D18 publication.
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


async def addressed_by_a_live_connection(
    plugin: Any, provider: str, account_id: str, legacy_name: str
) -> bool:
    """Does a non-revoked Connection still serve the legacy Profile's blob address?

    # WHY: an R1 rollback hands the pair back to the legacy Profile while the Connection that was
    # effective keeps addressing the Profile's blob (D5). Deleting that blob from the legacy side
    # would leave a live Connection with no credential (§5.3: owner checks address the actual
    # service/account address, not only the provider label).
    # AIDEV-NOTE: runs after the pair claim, so every writer that could add a Connection at this
    # address (the migrated authority, the backfill, the G1 bridge) is serialized on the marker.
    """
    locator = credential_locator_for(
        credential_service_provider_for(plugin, provider), account_id, legacy_name
    )
    rows = await OAuthConnection.filter(account_id=account_id, provider=provider).exclude(
        status="revoked"
    )
    return any(row.credential_locator == locator for row in rows)


class ProfileBackedCredentialAdmin:
    """The app-bound base of `ConnectionBackedCredentialAdmin`: the index, strategies, eviction."""

    def __init__(self, app: Any) -> None:
        # WHY the app, not the stores: `profile_index`, `credential_store` and
        # `{provider}_http_factory` are read LAZILY at call time — tests monkeypatch them onto
        # `app.state` after the app is built.
        self._app = app

    @property
    def _index(self) -> ProfileIndexStore:
        return self._app.state.profile_index

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
