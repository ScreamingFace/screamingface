"""Two harnesses for the provider-access PORT CONTRACT suite (OME-1200, A1 of OME-1138).

# FEATURE: the contract tests run unchanged over a pure in-memory fake
# (`_provider_access_fake.py`) and over the Profile-backed implementation on the real app, so
# any later backing must pass the same suite.
# AIDEV-NOTE: the harness hides HOW a state is seeded (a `Profile` row + blob today, a slot
# tomorrow) and HOW a side effect is observed (a recorder on the strategy cache and the plugin
# hook today); tests only name the situation. Keep Profile/Connection vocabulary inside this
# file and the fake.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any, Protocol, cast
from uuid import uuid4

from _provider_access_fake import PROVIDER, FakeHarness, FakeProviderAccess

from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.errors import AuthError
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.provider_access import ProviderAccess
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.anthropic_provider.plugin import PLUGIN as ANTHROPIC


class Harness(Protocol):
    # WHY properties, not attributes: a mutable attribute is INVARIANT, which would force every
    # harness to hold exactly `ProviderAccess`; the fake harness holds its concrete fake so the
    # tests can seed it. Read-only members let each harness hold its own implementation.
    @property
    def access(self) -> ProviderAccess: ...

    @property
    def account_id(self) -> str: ...

    def call(
        self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any
    ) -> Any: ...

    def seed_profile(
        self,
        *,
        name: str = "default",
        state: ProfileState = ProfileState.AUTHENTICATED,
        auth_type: str = "oauth",
        defaults: ProfileDefaults | None = None,
        credential: str | None = "tok",
    ) -> None: ...

    def seed_connection(
        self, *, label: str, auth_type: str = "oauth", credential: str | None = "ctok"
    ) -> str: ...

    def break_credential(self, credential_name: str) -> None: ...

    def malform_credential(self, credential_name: str) -> None:
        """Make the stored credential yield a non-mapping result instead of headers."""
        ...

    def fail_index_reads(self) -> None: ...

    def index_reads(self) -> int: ...

    def profile_state(self, name: str = "default") -> str | None: ...

    def connection_status(self, connection_id: str) -> str | None: ...

    # --- the side effects the contract names (spec §3.3 ops 4–5) ---

    def evicted(self) -> list[str]:
        """Credential names dropped from the shared strategy cache, in order."""
        ...

    def invalidated(self) -> list[str]:
        """Credential names whose provider session was invalidated, in order."""
        ...

    def last_used(self, connection_id: str) -> bool:
        """Whether the connection has been touched as used."""
        ...


# --- the Profile-backed implementation on the real app --------------------------------------


def _oauth_blob(access_token: str) -> str:
    expires_at_ms = int(time.time() * 1000) + 3_600_000
    token = {"access_token": access_token, "refresh_token": "rt", "token_type": "Bearer"}
    return json.dumps({**token, "expires_at_ms": expires_at_ms})


class _RaisingStrategy:
    """A cached strategy whose credential the provider has rejected."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_authorization_header(self) -> dict[str, str]:
        raise self._exc


class _MalformedStrategy:
    """A cached strategy whose result is not a header mapping at all."""

    async def get_authorization_header(self) -> Any:
        return None


class ProfileBackedHarness:
    def __init__(self, client: Any, credential_blobs: Any, monkeypatch: Any) -> None:
        self.client = client
        self.blobs = credential_blobs
        self.monkeypatch = monkeypatch
        self.access = client.app.state.provider_access
        self.account_id = client.get("/v1/auth/me").json()["id"]
        self._reads = 0
        self._fail = False
        self._evicted: list[str] = []
        self._invalidated: list[str] = []
        index = client.app.state.profile_index
        real_get = index.get

        async def counting_get(*args: Any, **kwargs: Any) -> Any:
            self._reads += 1
            if self._fail:
                raise RuntimeError("the profile index blob could not be decoded")
            return await real_get(*args, **kwargs)

        monkeypatch.setattr(index, "get", counting_get)

        # Recorders: the real cache still evicts; the real plugin hook is a no-op for Anthropic,
        # so recording the call IS the observable.
        cache = credential_strategy_cache(client.app)
        real_evict = cache.evict

        def recording_evict(credential_name: str) -> int:
            self._evicted.append(credential_name)
            return real_evict(credential_name)

        monkeypatch.setattr(cache, "evict", recording_evict)
        monkeypatch.setattr(ANTHROPIC, "invalidate_profile_session", self._invalidated.append)

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return self.client.portal.call(partial(fn, *args, **kwargs))

    def seed_profile(
        self,
        *,
        name: str = "default",
        state: ProfileState = ProfileState.AUTHENTICATED,
        auth_type: str = "oauth",
        defaults: ProfileDefaults | None = None,
        credential: str | None = "tok",
    ) -> None:
        if credential is not None:
            value = (
                _oauth_blob(credential)
                if auth_type == "oauth"
                else json.dumps({"auth_type": "api_key", "api_key": credential})
            )
            self.blobs.write(
                credential_service_for(credential_name_for(self.account_id, name)),
                "default",
                value,
            )
        idx = ProfileIndexStore(credential_store=self.blobs.store)
        self.call(
            idx.upsert,
            Profile(
                id=profile_id_for(self.account_id, PROVIDER, name),
                account_id=self.account_id,
                provider=PROVIDER,
                name=name,
                state=state,
                auth_type=cast(AuthType, auth_type),
                defaults=defaults or ProfileDefaults(),
            ),
        )

    def seed_connection(
        self, *, label: str, auth_type: str = "oauth", credential: str | None = "ctok"
    ) -> str:
        async def create() -> Any:
            store = OAuthConnectionStore()
            pending = await store.create_pending(
                account_id=self.account_id, provider=PROVIDER, label=label, connection_id=uuid4()
            )
            connection = await store.complete(pending, label=label, identity=None)
            if auth_type != "oauth":
                connection = await store.set_auth_type(connection, cast(AuthType, auth_type))
            return connection

        connection = self.call(create)
        if credential is not None:
            self.blobs.write(
                credential_service_for(credential_key_for(self.account_id, connection.id)),
                "default",
                _oauth_blob(credential),
            )
        return str(connection.id)

    def break_credential(self, credential_name: str) -> None:
        credential_strategy_cache(self.client.app).get_or_create(
            provider=PROVIDER,
            auth_type="oauth",
            credential_name=credential_name,
            build=lambda: _RaisingStrategy(AuthError("refresh rejected")),
        )

    def malform_credential(self, credential_name: str) -> None:
        credential_strategy_cache(self.client.app).get_or_create(
            provider=PROVIDER,
            auth_type="oauth",
            credential_name=credential_name,
            build=_MalformedStrategy,
        )

    def fail_index_reads(self) -> None:
        self._fail = True

    def index_reads(self) -> int:
        return self._reads

    def profile_state(self, name: str = "default") -> str | None:
        resp = self.client.get(f"/v1/auth/{PROVIDER}/profiles/{name}")
        return None if resp.status_code == 404 else resp.json()["state"]

    def _connection_row(self, connection_id: str) -> dict[str, Any] | None:
        rows = self.client.get("/v1/oauth/connections").json()["connections"]
        return next((row for row in rows if row["id"] == connection_id), None)

    def connection_status(self, connection_id: str) -> str | None:
        row = self._connection_row(connection_id)
        return None if row is None else row["status"]

    def evicted(self) -> list[str]:
        return list(self._evicted)

    def invalidated(self) -> list[str]:
        return list(self._invalidated)

    def last_used(self, connection_id: str) -> bool:
        row = self._connection_row(connection_id)
        return row is not None and row["last_used_at"] is not None


__all__ = [
    "ANTHROPIC",
    "PROVIDER",
    "FakeHarness",
    "FakeProviderAccess",
    "Harness",
    "ProfileBackedHarness",
]
