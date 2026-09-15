"""The pure in-memory witness of the provider-access PORT CONTRACT (OME-1200, A1 of OME-1138).

# FEATURE: the contract suite runs unchanged over this fake and over the Profile-backed
# implementation on the real app (`provider_access_harness.py`), so any later backing must pass
# the same suite. The fake models every side effect the contract names — eviction, marking,
# session invalidation, the last-used touch — so a test asserting one of them is meaningful on
# both witnesses.
# AIDEV-NOTE: keep this a SECOND implementation, not a mirror of the real one: it stores dicts,
# never rows, and records its writes in plain lists the fake harness reads back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from aigateway.core.oauth.store import credential_key_for
from aigateway.core.profile_models import (
    AuthMode,
    AuthType,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
)
from aigateway.core.provider_access import (
    Authorization,
    AvailabilityRow,
    CredentialTarget,
    RequestDefaults,
    ResolvePolicy,
    Selector,
    SelectorAmbiguous,
    SelectorUnknown,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    auth_mode,
    contract_auth_mode,
    reauth_url_for,
)

PROVIDER = "anthropic"


@dataclass
class _FakeProfile:
    state: ProfileState
    auth_type: str
    defaults: ProfileDefaults
    credential: str | None
    broken: bool = False
    malformed: bool = False


@dataclass
class _FakeConnection:
    id: str
    label: str
    status: str
    auth_type: str
    credential: str | None
    broken: bool = False
    malformed: bool = False
    used: bool = False


@dataclass
class FakeProviderAccess:
    """A second implementation of the port, over dicts — the contract's other witness."""

    profiles: dict[tuple[str, str, str], _FakeProfile] = field(default_factory=dict)
    connections: list[tuple[str, str, _FakeConnection]] = field(default_factory=list)
    reads: int = 0
    reads_fail: bool = False
    evicted: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)

    def _read(self, account_id: str, provider: str, name: str) -> _FakeProfile | None:
        self.reads += 1
        if self.reads_fail:
            raise RuntimeError("index unreadable")
        return self.profiles.get((account_id, provider, name))

    async def defaults_for(
        self, account_id: str, provider: str, selector: Selector
    ) -> RequestDefaults | None:
        try:
            profile = self._read(account_id, provider, selector.name)
        except Exception:
            return None
        return RequestDefaults() if profile is None else profile.defaults

    async def resolve(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy = ResolvePolicy.DISPATCH,
    ) -> CredentialTarget:
        profile = self._read(account_id, provider, selector.name)
        if profile is None:
            return self._resolve_connection(account_id, provider, selector, plugin, policy)
        if profile.state is ProfileState.PENDING:
            raise TargetPending(provider, selector.name)
        if profile.state is ProfileState.ERROR:
            raise TargetReauthRequired(
                provider,
                f"/v1/auth/{provider}/profiles/{selector.name}",
                requested=selector.name,
            )
        name = credential_name_for(account_id, selector.name)
        return CredentialTarget(
            kind="stored",
            auth_type=cast(AuthType, profile.auth_type),
            credential_name=name,
            context_stamp=f"acct:{account_id}|prof:{account_id}:{provider}:{selector.name}:"
            f"{profile.state.value}:-",
            reauth_url=reauth_url_for(provider, selector.name, cast(AuthType, profile.auth_type)),
            defaults=profile.defaults,
            _backing=("profile", (account_id, provider, selector.name)),
        )

    def _resolve_connection(
        self, account_id: str, provider: str, selector: Selector, plugin: Any, policy: Any
    ) -> CredentialTarget:
        active = [
            c
            for acct, prov, c in self.connections
            if acct == account_id and prov == provider and c.status == "active"
        ]
        chosen = next((c for c in active if c.label == selector.name), None)
        if chosen is None and active and selector.is_default and len(active) == 1:
            chosen = active[0]
        if chosen is not None:
            key = credential_key_for(account_id, UUID(chosen.id))
            return CredentialTarget(
                kind="stored",
                auth_type=cast(AuthType, chosen.auth_type),
                credential_name=key,
                context_stamp=f"acct:{account_id}|conn:{chosen.id}:{chosen.status}:-",
                reauth_url=reauth_url_for(
                    provider,
                    selector.name,
                    cast(AuthType, chosen.auth_type),
                    connection_id=chosen.id,
                ),
                defaults=RequestDefaults(),
                _backing=("connection", chosen.id),
            )
        if active and selector.is_default:
            raise SelectorAmbiguous(provider)
        if active:
            raise SelectorUnknown(provider, selector.name, tuple(c.label for c in active))
        chatless = getattr(plugin, "allows_chatless_profile", lambda: False)()
        if not chatless and not (policy is ResolvePolicy.DATASHEET and selector.is_default):
            raise TargetMissing(provider, selector.name)
        kind = "ambient" if plugin.profileless_auth_mode() is not None else "none"
        return CredentialTarget(
            kind=kind,
            auth_type="oauth",
            credential_name=None,
            context_stamp=f"acct:{account_id}|anon",
            reauth_url=None,
            defaults=RequestDefaults(),
            _backing=None,
        )

    def auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return auth_mode(target, plugin=plugin)

    def contract_auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return contract_auth_mode(target, plugin=plugin)

    async def authorize(self, target: CredentialTarget, *, plugin: Any, provider: str) -> Any:
        if target.kind != "stored":
            return Authorization(headers={}, credential_name=None, auth_type="oauth")
        row = self._row(target)
        name = str(target.credential_name)
        if row.credential is None:
            # A MISSING credential evicts and never invalidates; it marks a CONNECTION errored
            # but leaves a PROFILE authenticated (contract, mirroring today's two branches).
            self.evicted.append(name)
            if isinstance(row, _FakeConnection):
                self._mark_error(target)
            raise TargetReauthRequired(
                provider, str(target.reauth_url), message="No credential stored"
            )
        if row.broken:
            self.evicted.append(name)
            self._mark_error(target)
            self.invalidated.append(name)
            raise TargetReauthRequired(provider, str(target.reauth_url), message="rejected")
        if row.malformed:
            # The result is checked to be a header mapping BEFORE any touch (contract, F5).
            raise TypeError("credential result is not a header mapping")
        if isinstance(row, _FakeConnection):
            row.used = True
        return Authorization(
            headers={"Authorization": f"Bearer {row.credential}"},
            credential_name=target.credential_name,
            auth_type=target.auth_type,
        )

    async def record_dispatch_failure(
        self, target: CredentialTarget, status: int, detail: Any, *, plugin: Any
    ) -> dict[str, Any] | None:
        if target.kind != "stored":
            return None
        body = detail if isinstance(detail, dict) else {"message": str(detail)}
        name = str(target.credential_name)
        self.evicted.append(name)
        self._mark_error(target)
        self.invalidated.append(name)
        backing_kind, _ = target._backing
        if backing_kind == "connection":
            return None
        return {
            "code": body.get("code", "auth_required"),
            "message": body.get("message", str(detail)),
            "reauth_url": body.get("reauth_url", target.reauth_url),
        }

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        states: dict[str, set[str]] = {}
        for (acct, provider, _), profile in self.profiles.items():
            if acct == account_id:
                states.setdefault(provider, set()).add(profile.state.value)
        rows = []
        for provider in sorted(states):
            seen = states[provider]
            status = (
                "connected"
                if "authenticated" in seen
                else "pending"
                if "pending" in seen
                else "error"
            )
            rows.append(AvailabilityRow(provider, status))
        return tuple(rows)

    def _row(self, target: CredentialTarget) -> Any:
        backing_kind, key = target._backing
        if backing_kind == "profile":
            return self.profiles[key]
        return next(c for _, _, c in self.connections if c.id == key)

    def _mark_error(self, target: CredentialTarget) -> None:
        backing_kind, key = target._backing
        if backing_kind == "profile":
            self.profiles[key].state = ProfileState.ERROR
        else:
            self._row(target).status = "error"


class FakeHarness:
    account_id = "acct-fake"

    def __init__(self) -> None:
        self.access = FakeProviderAccess()

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    def seed_profile(
        self,
        *,
        name: str = "default",
        state: ProfileState = ProfileState.AUTHENTICATED,
        auth_type: str = "oauth",
        defaults: ProfileDefaults | None = None,
        credential: str | None = "tok",
    ) -> None:
        self.access.profiles[(self.account_id, PROVIDER, name)] = _FakeProfile(
            state, auth_type, defaults or ProfileDefaults(), credential
        )

    def seed_connection(
        self, *, label: str, auth_type: str = "oauth", credential: str | None = "ctok"
    ) -> str:
        connection = _FakeConnection(str(uuid4()), label, "active", auth_type, credential)
        self.access.connections.append((self.account_id, PROVIDER, connection))
        return connection.id

    def break_credential(self, credential_name: str) -> None:
        for (acct, _, name), profile in self.access.profiles.items():
            if credential_name_for(acct, name) == credential_name:
                profile.broken = True
        for acct, _, connection in self.access.connections:
            if credential_key_for(acct, UUID(connection.id)) == credential_name:
                connection.broken = True

    def malform_credential(self, credential_name: str) -> None:
        for (acct, _, name), profile in self.access.profiles.items():
            if credential_name_for(acct, name) == credential_name:
                profile.malformed = True
        for acct, _, connection in self.access.connections:
            if credential_key_for(acct, UUID(connection.id)) == credential_name:
                connection.malformed = True

    def fail_index_reads(self) -> None:
        self.access.reads_fail = True

    def index_reads(self) -> int:
        return self.access.reads

    def profile_state(self, name: str = "default") -> str | None:
        profile = self.access.profiles.get((self.account_id, PROVIDER, name))
        return None if profile is None else profile.state.value

    def connection_status(self, connection_id: str) -> str | None:
        return next(
            (c.status for _, _, c in self.access.connections if c.id == connection_id), None
        )

    def evicted(self) -> list[str]:
        return list(self.access.evicted)

    def invalidated(self) -> list[str]:
        return list(self.access.invalidated)

    def last_used(self, connection_id: str) -> bool:
        return next(c.used for _, _, c in self.access.connections if c.id == connection_id)


__all__ = ["PROVIDER", "FakeHarness", "FakeProviderAccess"]
