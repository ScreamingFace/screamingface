"""The pure in-memory witness of the provider-access PORT CONTRACT (OME-1200, A1 of OME-1138).

# FEATURE: the contract suite runs unchanged over this fake and over the real app
# (`connection_backed_harness.py`), so any backing must pass the same suite. The fake models
# every side effect the contract names — eviction, marking, session invalidation, the last-used
# touch — so a test asserting one of them is meaningful on both witnesses.
# FEATURE: OME-1138 close-out, L4a — the fake speaks Connections only, for the default selector
# only. "A stored credential" is a pair's effective Connection, the row a `migrated` marker names,
# addressed at the credential NAME, exactly as the real harness seeds a migrated pair; any other
# row is a plain Connection the default selector serves only as the pair's one active row.
# WHY keep this a SECOND implementation, not a mirror of the real one: it stores dicts, never rows,
# and records its writes in plain lists the fake harness reads back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from aigateway.core.auth_types import AuthMode, AuthType
from aigateway.core.credential_blob import DispatchObservation, OperationalOutcome
from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.provider_access import (
    Authorization,
    AvailabilityRow,
    AvailabilityStatus,
    CredentialTarget,
    ResolvePolicy,
    Selector,
    SelectorAmbiguous,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
    auth_mode,
    contract_auth_mode,
    reauth_url_for,
)
from tests.unit.seed_state import SeedState

PROVIDER = "anthropic"

_STATUS_FOR_STATE = {
    SeedState.AUTHENTICATED: "active",
    SeedState.PENDING: "pending",
    SeedState.ERROR: "error",
}
_STATE_FOR_STATUS = {status: state.value for state, status in _STATUS_FOR_STATE.items()}
_LISTED: dict[str, AvailabilityStatus] = {
    "active": "connected",
    "pending": "pending",
    "error": "error",
}


@dataclass
class _FakeConnection:
    id: str
    label: str
    status: str
    auth_type: str
    credential: str | None
    # WHY: a stored credential's row reads the blob at the credential NAME (the migrated locator);
    # a plain row reads its own UUID address.
    address: str | None = None
    broken: bool = False
    malformed: bool = False
    used: bool = False


@dataclass
class FakeProviderAccess:
    """A second implementation of the port, over dicts — the contract's other witness."""

    connections: list[tuple[str, str, _FakeConnection]] = field(default_factory=list)
    # WHY a reference per pair: it is the `migrated` marker, (account, provider) → the effective
    # Connection's id, which resolve serves before any other row of the pair.
    references: dict[tuple[str, str], str] = field(default_factory=dict)
    evicted: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)

    def _rows(self, account_id: str, provider: str) -> list[_FakeConnection]:
        return [c for acct, prov, c in self.connections if acct == account_id and prov == provider]

    def _effective(self, account_id: str, provider: str) -> _FakeConnection | None:
        reference = self.references.get((account_id, provider))
        return next((c for c in self._rows(account_id, provider) if c.id == reference), None)

    async def resolve(
        self,
        account_id: str,
        provider: str,
        selector: Selector,
        *,
        plugin: Any,
        policy: ResolvePolicy = ResolvePolicy.DISPATCH,
    ) -> CredentialTarget:
        effective = self._effective(account_id, provider)
        if effective is None:
            return self._resolve_active(account_id, provider, selector, plugin, policy)
        # INVARIANT: an unusable effective credential refuses; it never falls back to another row.
        if effective.status == "pending":
            raise TargetPending(provider, selector.name)
        if effective.status != "active":
            raise TargetReauthRequired(provider, reauth_url_for(None), requested=selector.name)
        return self._target(account_id, effective, str(effective.address), kind="effective")

    def _resolve_active(
        self, account_id: str, provider: str, selector: Selector, plugin: Any, policy: Any
    ) -> CredentialTarget:
        active = [c for c in self._rows(account_id, provider) if c.status == "active"]
        if len(active) > 1:
            raise SelectorAmbiguous(provider)
        if active:
            chosen = active[0]
            key = credential_key_for(account_id, UUID(chosen.id))
            return self._target(account_id, chosen, key, kind="connection")
        chatless = getattr(plugin, "allows_chatless_credential", lambda: False)()
        if not chatless and not (policy is ResolvePolicy.DATASHEET and selector.is_default):
            raise TargetMissing(provider, selector.name)
        kind = "ambient" if plugin.credentialless_auth_mode() is not None else "none"
        return CredentialTarget(
            kind=kind,
            auth_type="oauth",
            credential_name=None,
            context_stamp=f"acct:{account_id}|anon",
            reauth_url=None,
            _backing=None,
        )

    def _target(
        self, account_id: str, chosen: _FakeConnection, credential_name: str, *, kind: str
    ) -> CredentialTarget:
        return CredentialTarget(
            kind="stored",
            auth_type=cast(AuthType, chosen.auth_type),
            credential_name=credential_name,
            context_stamp=f"acct:{account_id}|conn:{chosen.id}:{chosen.status}:-",
            reauth_url=reauth_url_for(cast(AuthType, chosen.auth_type), connection_id=chosen.id),
            _backing=(kind, chosen.id),
        )

    def auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return auth_mode(target, plugin=plugin)

    def contract_auth_mode(self, target: CredentialTarget, plugin: Any) -> AuthMode:
        return contract_auth_mode(target, plugin=plugin)

    async def authorize(self, target: CredentialTarget, *, plugin: Any, provider: str) -> Any:
        if target.kind != "stored":
            return Authorization(headers={}, credential_name=None, auth_type="oauth")
        backing_kind, _ = target._backing
        row = self._row(target)
        name = str(target.credential_name)
        if row.credential is None:
            # A MISSING credential evicts and never invalidates; it marks a plain Connection errored
            # but leaves an effective one as it is (contract, mirroring the real two branches).
            self.evicted.append(name)
            if backing_kind == "connection":
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
        # WHY every backing: the effective Connection is a Connection, touched like any other.
        row.used = True
        return Authorization(
            headers={"Authorization": f"Bearer {row.credential}"},
            credential_name=target.credential_name,
            auth_type=target.auth_type,
        )

    async def begin_dispatch(
        self, target: CredentialTarget, *, plugin: Any, provider: str
    ) -> DispatchObservation | None:
        del target, plugin, provider
        return None

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

    async def record_dispatch_outcome(
        self,
        target: CredentialTarget,
        observation: DispatchObservation,
        outcome: OperationalOutcome,
        detail: Any,
        *,
        plugin: Any,
    ) -> dict[str, Any] | None:
        del target, observation, outcome, detail, plugin
        return None

    async def availability(self, account_id: str) -> tuple[AvailabilityRow, ...]:
        providers = sorted({prov for acct, prov, _ in self.connections if acct == account_id})
        return tuple(
            AvailabilityRow(provider, self._status(account_id, provider)) for provider in providers
        )

    def _status(self, account_id: str, provider: str) -> AvailabilityStatus:
        """What the default resolve finds for the pair, in the listing's vocabulary."""
        effective = self._effective(account_id, provider)
        if effective is not None:
            return _LISTED.get(effective.status, "not_connected")
        return _active_status(self._rows(account_id, provider))

    def _row(self, target: CredentialTarget) -> _FakeConnection:
        _, key = target._backing
        return next(c for _, _, c in self.connections if c.id == key)

    def _mark_error(self, target: CredentialTarget) -> None:
        self._row(target).status = "error"


def _active_status(rows: Sequence[_FakeConnection]) -> AvailabilityStatus:
    active = [c for c in rows if c.status == "active"]
    if active:
        return "connected" if len(active) == 1 else "error"
    statuses = {c.status for c in rows}
    if "pending" in statuses:
        return "pending"
    return "error" if "error" in statuses else "not_connected"


class FakeHarness:
    account_id = "acct-fake"

    def __init__(self) -> None:
        self.access = FakeProviderAccess()
        self.migrated: dict[str, str] = {}

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    def seed_credential(
        self,
        *,
        name: str = "default",
        state: SeedState = SeedState.AUTHENTICATED,
        auth_type: str = "oauth",
        credential: str | None = "tok",
    ) -> None:
        """The situation "a stored credential in `state`" — as the pair's effective Connection."""
        connection = _FakeConnection(
            str(uuid4()),
            name,
            _STATUS_FOR_STATE[state],
            auth_type,
            credential,
            address=credential_name_for(self.account_id, name),
        )
        self.access.connections.append((self.account_id, PROVIDER, connection))
        self.access.references[(self.account_id, PROVIDER)] = connection.id
        self.migrated[name] = connection.id

    def seed_connection(
        self, *, label: str, auth_type: str = "oauth", credential: str | None = "ctok"
    ) -> str:
        connection = _FakeConnection(str(uuid4()), label, "active", auth_type, credential)
        self.access.connections.append((self.account_id, PROVIDER, connection))
        return connection.id

    def _named(self, credential_name: str) -> list[_FakeConnection]:
        return [
            connection
            for acct, _, connection in self.access.connections
            if credential_name
            in (connection.address, credential_key_for(acct, UUID(connection.id)))
        ]

    def break_credential(self, credential_name: str) -> None:
        for connection in self._named(credential_name):
            connection.broken = True

    def malform_credential(self, credential_name: str) -> None:
        for connection in self._named(credential_name):
            connection.malformed = True

    def credential_state(self, name: str = "default") -> str | None:
        """The stored credential's state in the seed vocabulary: its Connection's status."""
        connection_id = self.migrated.get(name)
        status = None if connection_id is None else self.connection_status(connection_id)
        return None if status is None else _STATE_FOR_STATUS.get(status, status)

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
