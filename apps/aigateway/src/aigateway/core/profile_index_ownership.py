"""Ownership rules for the profile index — pure predicates, no I/O.

FEATURE: one place that decides whether a publication still belongs to the owner who
started it, so every publication path enforces the same fence.

WHY its own module: these rules are pure predicates over a ``ProfileIndex`` document,
while ``ProfileIndexStore`` is already at the source-file size limit. Keeping the rules
next door preserves one readable CAS implementation without growing that store again.

AIDEV-NOTE: every function here is called from INSIDE an ``ORMStore.mutate`` callback.
That is what makes them safe across workers: the callback re-runs against the latest
committed index row on every CAS retry, so a check that passed against a stale snapshot
is re-evaluated before anything commits. Never make one of these async, and never make
one read from a store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .profile_models import AuthType, Profile, ProfileIndex


class ProfileTransitionConflict(RuntimeError):
    """Raised when a stale authentication flow no longer owns a pending profile."""


class CredentialOwnershipConflict(ProfileTransitionConflict):
    """The profile's credential owner changed since the caller read it.

    A ``ProfileTransitionConflict`` by inheritance, so every existing handler keeps
    treating it as the retryable conflict it is; a distinct type only so the refresh
    path can report WHICH fence refused it (OME-1026 adversarial B2).
    """


def bump_credential_generation(idx: ProfileIndex, profile_id: str) -> None:
    """Advance ``profile_id``'s credential generation inside the caller's index CAS.

    INVARIANT (OME-1026 F3): the generation is an OWNERSHIP/AUTHENTICATION fence, not a
    version of every refreshed access-token byte. It advances when the credential's
    OWNER is replaced — an API key set or replaced, an OAuth re-authentication, an
    auth-type switch, a delete and recreate — and must NOT advance for a routine token
    refresh that leaves the same authenticated owner in place.
    # WHY the narrower contract is the correct one and not merely the cheaper one: a
    # routine refresh writes the credential blob through the provider strategy and could
    # only bump afterwards, so "version every byte" needed two durable writes with no
    # transaction around them — a crash in between left a blob holding a new token while
    # every cached snapshot still named the old generation. A refresh that is not an
    # ownership event has nothing to publish, which removes the window rather than
    # trying to make two writes atomic. The entitlements a private catalog describes
    # belong to the owner; rotating that owner's token does not change them.

    INVARIANT (OME-1026 F3): called from INSIDE a ``mutate`` callback, which re-runs
    against the latest committed row on every CAS retry — so the stored value is
    strictly greater than any generation that has ever committed for this profile.
    That is what makes it collision-free between workers, where a ``datetime.now()``
    stamp was not.

    INVARIANT: never cleared on delete. Clearing would restart at 1, and a snapshot
    cached under the ORIGINAL generation 1 — on this worker or another — would match a
    recreated profile of the same name exactly. A stale map entry costs a few bytes; a
    rewound generation costs correctness.
    """
    idx.credential_generations[profile_id] = idx.credential_generations.get(profile_id, 0) + 1


def require_expected_ownership(
    idx: ProfileIndex,
    current: Profile | None,
    *,
    profile_id: str,
    expected_generation: int | None,
    expected_auth_type: AuthType | None,
) -> None:
    """Refuse a publication whose owner is no longer the one the caller read.

    # INVARIANT: called from inside a ``mutate`` mutator, so it sees the LATEST committed
    # index on every CAS retry rather than a snapshot the caller took earlier.
    """
    if expected_generation is not None:
        if current is None:
            raise CredentialOwnershipConflict("profile was concurrently deleted")
        if idx.credential_generations.get(profile_id, 0) != expected_generation:
            raise CredentialOwnershipConflict("credential ownership generation changed")
    if expected_auth_type is not None:
        if current is None:
            raise CredentialOwnershipConflict("profile was concurrently deleted")
        if current.auth_type != expected_auth_type:
            raise CredentialOwnershipConflict("profile authentication type changed")
