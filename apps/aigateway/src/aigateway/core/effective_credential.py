"""OME-1026 — ONE effective provider credential per account, resolved implicitly.

FEATURE: the confirmed product model has one implicit credential per provider. The
Python Client never selects a profile (`sf.models.list()` sends no ``X-Profile``),
so the gateway resolves each provider's effective credential automatically:

- hosted mode represents it as the provider's Profile named ``default``;
- local mode represents it as the provider's sole ACTIVE Connection, whatever its
  label — exactly the fallback chat has always applied.

This module is the ONE place that policy lives. ``GET /v1/models``,
``GET /v1/model-parameters`` and chat dispatch all resolve through it, so the three
surfaces cannot disagree about whose credential a request is served under.

INVARIANT (never an arbitrary pick): more than one active Connection with no
explicit label selection is AMBIGUOUS. The resolver reports that outcome instead of
choosing, so no discovery egress and no dispatch can ever be funded by a guess.

INVARIANT (non-secret identity): ``EffectiveCredential.credential_revision`` is
derived from durable OWNERSHIP metadata only — never from key material and never
from a wall clock. It is the private snapshot cache identity, so anything
credential-dependent in it would leak into keys, logs and comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from .oauth.store import credential_key_for
from .profile_models import ProfileDefaults, ProfileState, credential_name_for
from .profile_snapshot_store import profile_credential_revision

if TYPE_CHECKING:
    from .oauth.models import OAuthConnection
    from .oauth.store import OAuthConnectionStore
    from .profile_index import ProfileIndexStore
    from .profile_models import AuthType, Profile

DEFAULT_PROFILE_NAME = "default"


@dataclass(frozen=True)
class EffectiveCredential:
    """The resolved effective credential target for one (account, provider).

    Exactly one of ``profile``/``connection`` is set. ``profile_name`` is the
    LOGICAL name: ``default`` for every implicit and Connection-backed resolution,
    so the private catalog identity of the one-credential-per-provider product
    model is stable across hosted/local representations and label renames.

    # WHY the real ORM objects ride along instead of a synthesized Profile: a
    # Connection has its own lifecycle and revision semantics, and consumers (chat
    # error mapping, dispatch strategy selection) genuinely branch on the backing.
    # A pretend Profile would hide that difference, not solve it.
    """

    provider: str
    account_id: str
    profile_name: str
    auth_type: AuthType
    authenticated: bool
    defaults: ProfileDefaults
    profile: Profile | None
    connection: OAuthConnection | None
    # Non-secret durable cache identity token (see the module INVARIANT).
    credential_revision: str
    # The credential-blob slot a DEFERRED auth provider reads — carrying the name
    # instead of headers is what keeps warm-cache and refusal paths decryption-free.
    credential_name: str


@dataclass(frozen=True)
class AmbiguousCredential:
    """More than one active Connection and nothing selected one: refuse to guess."""

    provider: str
    valid_labels: tuple[str, ...]


@dataclass(frozen=True)
class UnknownConnectionLabel:
    """An explicit label matched no active Connection: report what would."""

    provider: str
    requested_label: str
    valid_labels: tuple[str, ...]


# ``None`` means zero candidates: no Profile and no active Connection. Callers
# degrade to seeds / credential-free behavior.
CredentialResolution = EffectiveCredential | AmbiguousCredential | UnknownConnectionLabel | None


class DiscoveryCredentialTarget(Protocol):
    """What the private catalog needs to know about ONE effective credential.

    Satisfied structurally by ``EffectiveCredential`` (Profile- OR Connection-
    backed) and by ``profile_discovery_target`` below — the catalog itself never
    learns which backing it is.

    # INVARIANT: ``credential_revision`` is the caller's durable NON-SECRET
    # ownership token. It joins the private cache key verbatim, so snapshot
    # isolation rides on the caller deriving it from ownership metadata, never
    # from key material.
    # WHY read-only properties, not attributes: a plain protocol attribute demands
    # WRITABLE members, which a frozen dataclass cannot provide.
    """

    @property
    def profile_name(self) -> str: ...
    @property
    def auth_type(self) -> AuthType: ...
    @property
    def authenticated(self) -> bool: ...
    @property
    def credential_revision(self) -> str: ...


@dataclass(frozen=True)
class _ProfileDiscoveryTarget:
    profile_name: str
    auth_type: AuthType
    authenticated: bool
    credential_revision: str


def profile_discovery_target(
    profile: Profile, credential_generation: int
) -> _ProfileDiscoveryTarget:
    """The target view of a bare Profile + its durable credential generation."""
    return _ProfileDiscoveryTarget(
        profile_name=profile.name,
        auth_type=profile.auth_type,
        authenticated=profile.state is ProfileState.AUTHENTICATED,
        credential_revision=profile_credential_revision(profile, credential_generation),
    )


def connection_credential_revision(connection: OAuthConnection) -> str:
    """A NON-SECRET cache identity token for a Connection-backed credential.

    The connection ``id`` is a fresh UUID per row, so delete/recreate can never
    reuse a prior identity; ``credential_generation`` is the durable fence the
    store publishes for API-key creation and bumps atomically when REPLACING the
    key on the same row, retiring the old identity. Generic OAuth activation and
    refresh preserve it. Structurally distinct from the Profile revision
    (``{auth_type}@gen{n}``) via the ``conn:`` segment, so a hosted Profile and a
    local Connection under the same logical name can never alias snapshots.
    """
    auth_type = connection.auth_type or "oauth"
    return f"{auth_type}@conn:{connection.id}@gen{connection.credential_generation or 0}"


async def resolve_effective_credential(
    *,
    account_id: str,
    provider: str,
    profile_name: str = DEFAULT_PROFILE_NAME,
    profile_index: ProfileIndexStore,
    connections: OAuthConnectionStore,
) -> CredentialResolution:
    """Resolve the account's effective credential for ``provider``.

    Resolution order (chat's long-standing policy, now shared):

    1. the Profile named ``profile_name`` — any state; the CALLER decides what a
       PENDING/ERROR profile means for its surface (chat raises, listing lets the
       private catalog refuse before any credential is read);
    2. for the implicit ``default`` name: the SOLE active Connection, regardless
       of label; multiple active Connections are ambiguous;
    3. for a non-default explicit name: the active Connection with that label;
    4. otherwise a structured unknown-label refusal or ``None``.
    """
    found = await profile_index.get_with_credential_generation(account_id, provider, profile_name)
    if found is not None:
        profile, credential_generation = found
        return EffectiveCredential(
            provider=provider,
            account_id=account_id,
            profile_name=profile.name,
            auth_type=profile.auth_type,
            authenticated=profile.state is ProfileState.AUTHENTICATED,
            defaults=profile.defaults,
            profile=profile,
            connection=None,
            credential_revision=profile_credential_revision(profile, credential_generation),
            credential_name=credential_name_for(account_id, profile.name),
        )

    active = await connections.list(account_id, provider=provider, status="active")
    if not active:
        return None
    if profile_name == DEFAULT_PROFILE_NAME:
        if len(active) == 1:
            return _connection_backed(account_id, provider, active[0])
        return AmbiguousCredential(
            provider=provider,
            valid_labels=tuple(connection.label for connection in active),
        )
    for connection in active:
        if connection.label == profile_name:
            return _connection_backed(account_id, provider, connection)
    return UnknownConnectionLabel(
        provider=provider,
        requested_label=profile_name,
        valid_labels=tuple(connection.label for connection in active),
    )


def _connection_backed(
    account_id: str, provider: str, connection: OAuthConnection
) -> EffectiveCredential:
    return EffectiveCredential(
        provider=provider,
        account_id=account_id,
        # The LOGICAL name (see EffectiveCredential): one credential per provider,
        # so every Connection-backed resolution shares the ``default`` identity.
        profile_name=DEFAULT_PROFILE_NAME,
        # WHY the cast: tortoise-orm >=1.1.8 types CharField as `str`; the stored
        # column is a bare CharField, so narrowing it back to AuthType is ours to
        # assert. `or "oauth"` keeps chat's documented fallback for an empty value.
        auth_type=cast("AuthType", connection.auth_type or "oauth"),
        # Only ACTIVE connections are listed above, and active means its credential
        # is published and usable — the Connection analogue of AUTHENTICATED.
        authenticated=True,
        defaults=ProfileDefaults(),
        profile=None,
        connection=connection,
        credential_revision=connection_credential_revision(connection),
        credential_name=credential_key_for(account_id, connection.id),
    )
