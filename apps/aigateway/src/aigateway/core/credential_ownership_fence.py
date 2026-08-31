"""OME-1026 (F3) — the ownership fence around a manual profile refresh.

FEATURE: a profile credential refresh that cannot be published by whoever no longer
owns the profile.

The manual ``POST /refresh`` route owns a publication transaction, so
:class:`BufferedRefreshCredentialStore` defers every provider write into that
transaction. Publication then checks both durable facts: the profile index must still
carry the expected owner, and the credential bytes must still be the ones the refresh
read.

INVARIANT (the defect the MANUAL-path store closes): a provider strategy PERSISTS the
refreshed credential inside ``_refresh_credential`` — before the profile-index publication is even
attempted. So a refresh that started under ownership generation N and returned from the
provider after a replacement committed at N+1 wrote its credential blob over the new
owner's, and then restored the previous owner's profile metadata through the
presence-only ``upsert``. Removing the routine-refresh generation bump did not close
this: the two writes are still two writes, and only the second one was fenced.

INVARIANT (the shape of that fix): a check performed AFTER the credential has been
written is not enough, so on the manual path nothing is written during the refresh at
all. :class:`BufferedRefreshCredentialStore` buffers what the provider hands it and
replays it under the caller's publication transaction, where the credential CAS (bytes
unchanged since the pre-refresh read) sits beside the profile-index CAS (presence +
expected generation + expected auth type).
Either check failing rolls both back.

# WHY buffering there and not a compare-and-set at write time: an UNORDERED CAS at write
# time would take the CREDENTIAL row lock before the INDEX row lock, inverting the order
# ``upsert_api_key_profile`` and ``delete_profile_for_account`` deliberately share
# (OME-307 Blocker 3). Two writers taking two rows in opposite orders is a deadlock on
# any store with row locks. Buffering lets publication keep the established order.
# WHY not an in-process lock: a replacement can be published by a DIFFERENT worker, so
# the only serializer that means anything is the durable compare-and-set.
# AIDEV-NOTE: the buffered value is deliberately NOT visible to reads through this
# store. Every provider strategy here writes last and returns (verified across
# anthropic, codex, gemini, antigravity), and each keeps its own in-memory ``_cached``
# copy, so nothing in a refresh reads back what it just wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from .credential_blob.store import CredentialBlobStore
    from .profile_models import AuthType

_Slot = tuple[str, str]


class CredentialOwnerChanged(Exception):
    """The durable credential this refresh was based on is no longer the current one.

    Raised at publication time, so the caller's transaction rolls back and the new
    owner's credential, profile row, generation and private listing are all untouched.
    """


@dataclass(frozen=True)
class ExpectedOwnership:
    """Who owned the profile when a refresh began.

    Captured BEFORE the provider call — the whole point is that every field is read
    from the durable store while the refresh still legitimately owned the profile.

    # AIDEV-NOTE: ``profile_id`` already encodes account, provider and name
    # (``profile_id_for``), so it is the field the index CAS keys on; the three are kept
    # separately because a conflict report that names them is far easier to read in a
    # log than one id, and because they are what the caller already has in hand.
    """

    profile_id: str
    account_id: str
    provider: str
    profile_name: str
    auth_type: AuthType
    credential_generation: int


class BufferedRefreshCredentialStore:
    """A credential store that defers a refresh's writes to an ownership-checked publish.

    Reads, deletes and mutations pass straight through — only ``write`` is buffered,
    because ``write`` is the one operation a stale refresh could use to overwrite the
    new owner's credential.
    """

    def __init__(self, inner: CredentialBlobStore) -> None:
        self._inner = inner
        self._baseline: dict[_Slot, str | None] = {}
        self._buffered: dict[_Slot, str] = {}

    @property
    def has_buffered_write(self) -> bool:
        """Whether the refresh produced new credential bytes to publish.

        An api-key "refresh" only re-reads the stored key, so it produces none — and
        publication then touches the credential store not at all.
        """
        return bool(self._buffered)

    async def read(self, service: str, account: str) -> str | None:
        value = await self._inner.read(service, account)
        # INVARIANT: the baseline is recorded ONCE per slot. A later read must never move
        # it forward — a second read could return the REPLACEMENT's bytes, and the fence
        # would then cheerfully overwrite exactly what it exists to protect.
        self._baseline.setdefault((service, account), value)
        return value

    async def write(self, service: str, account: str, value: str) -> None:
        self._buffered[(service, account)] = value

    async def delete(self, service: str, account: str) -> None:
        await self._inner.delete(service, account)

    async def mutate(
        self, service: str, account: str, mutator: Callable[[str | None], str | None]
    ) -> None:
        await self._inner.mutate(service, account, mutator)

    async def publish(self) -> None:
        """Write every buffered value, refusing any slot that changed under us.

        Call this INSIDE the publication transaction, after the profile-index CAS, so
        the two conditional writes commit together or not at all.

        Raises :class:`CredentialOwnerChanged` when the durable bytes are no longer the
        ones this refresh read — a replaced key, a re-authentication, an auth-type
        switch, or a delete that removed the blob entirely.
        """
        for slot, value in self._buffered.items():
            service, account = slot
            if slot not in self._baseline:
                # A refresh that wrote a slot it never read has no baseline to check, so
                # it cannot be published safely. Refusing is the safe direction.
                raise CredentialOwnerChanged(
                    f"refresh wrote credential slot {service!r} it never read"
                )
            baseline = self._baseline[slot]

            def _compare_and_set(
                current: str | None, *, expected: str | None = baseline, new: str = value
            ) -> str:
                if current != expected:
                    raise CredentialOwnerChanged(
                        "the credential changed while this refresh was in flight"
                    )
                return new

            await self._inner.mutate(service, account, _compare_and_set)
        self._buffered.clear()
