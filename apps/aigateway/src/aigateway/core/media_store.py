"""The gateway's in-memory file store for uploaded Case files, scoped to one run (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4). The Engine uploads each Case file (a
picture or PDF of a Benchmark question) once per run (`routes/blobs.py`); each later model call
names the file by a **blob reference**, `blob:sha256/<64 hex>`. The chat route (PR 5) looks the
reference up here, inside the call's upstream slot, and puts the stored base64 into the request
it sends to the provider.

INVARIANT (decision 3): a SHA-256 alone never reaches a file. The gateway believes `X-User-Email`
from every pod that can reach port 9105, and the Runner, which executes Benchmark scorer code, is
one of them; a file's SHA-256 is guessable whenever its content is (a public dataset). So every
file is stored under a **scope**: the caller's account id plus the SHA-256 of a random per-run
token the Engine mints and sends with the upload and with every call. A lookup from another run,
another caller, or with no token finds nothing.
INVARIANT: memory only. Nothing here is ever written to disk; a restart forgets every file, and
the Engine uploads again (PR 8).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .errors import AigwError


@dataclass(frozen=True, slots=True)
class BlobScope:
    """Who may use a stored file: one caller, during one run (named by its token's hash)."""

    caller: str
    token_hash: str

    @classmethod
    def of(cls, caller: object, token: str | None) -> BlobScope | None:
        """The scope of this caller's run, or ``None`` when no token was sent.

        WHY ``None`` and not a scope with an empty token: a missing token must never become one
        scope that every token-less caller shares.
        WHY a hash of the token: the store keeps the scope for the run's whole life, so it keeps
        the hash, not the token itself; a heap dump or a repr then holds nothing a caller could
        present.
        """
        if token is None or not token.strip():
            return None
        token_hash: str = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return cls(caller=str(caller), token_hash=token_hash)

    def __repr__(self) -> str:
        return f"BlobScope(caller={self.caller}, token_hash={self.token_hash[:8]}…)"


@dataclass(frozen=True, slots=True)
class StoredMedia:
    """One stored file in the form a provider request needs: its base64 text, type and size."""

    media_type: str
    # The decoded file's size in bytes (what the reference part's `x_size` names), not the
    # base64 length.
    size_bytes: int
    base64_text: str

    def __repr__(self) -> str:
        # INVARIANT: a repr (a traceback, a debug line) never carries the file's bytes.
        return f"StoredMedia(media_type={self.media_type}, size_bytes={self.size_bytes})"


class MediaOverBudget(AigwError, ValueError):
    """One file's base64 is larger than the whole store; settings keep this from happening."""


class MediaLookup(Protocol):
    """The read side the chat route (PR 5) depends on: a file by scope and digest, or nothing."""

    def get(self, scope: BlobScope | None, digest: str) -> StoredMedia | None:
        """The file stored under exactly this scope and digest, or ``None``."""
        ...


#: The bytes charged for each stored file on top of its base64 text: its entry, its 64-character
#: digest, its key and its place in the least-recently-used order. WHY: a review of #2067
#: (27 Nov 2026) measured about 417 bytes of Python objects per stored file (tracemalloc,
#: 200,000 seven-byte files); charging only the base64 let 4-byte uploads hold about 35 times
#: the budget in real memory. 1024 leaves room over that measurement.
ENTRY_OVERHEAD_BYTES: int = 1024
#: The bytes charged for each live scope (one run's record: its key, its expiry and its set of
#: digests), released when the scope's last file goes. WHY: a caller can send a fresh token on
#: every upload, so an uncharged scope record is memory the budget never sees.
SCOPE_OVERHEAD_BYTES: int = 1024


def entry_cost(media: StoredMedia) -> int:
    """The bytes one stored file is charged: its base64 text plus its bookkeeping."""
    return len(media.base64_text) + ENTRY_OVERHEAD_BYTES


class MediaStore:
    """Holds each uploaded file's base64 once per scope, in memory, within a byte budget.

    In one line: a map from (scope, digest) to the file's base64 text, ordered by last use, whose
    charged bytes never pass the budget.

    What a byte of budget pays for: each file is charged its base64 length plus
    ``ENTRY_OVERHEAD_BYTES``, and each live scope ``SCOPE_OVERHEAD_BYTES``. INVARIANT: the
    charge covers every object the store keeps, so a flood of tiny files or fresh tokens fills
    the budget and drops older files instead of growing memory past it.

    How it behaves, in the order a run meets it:

    1. ``put`` at upload: a scope met for the first time is charged its overhead and gets an
       expiry of now + ``scope_ttl_seconds``; uploading more files later in the run never extends
       it. Expired scopes are dropped first, then least recently used files until the new one
       fits. A scope whose last file is dropped is forgotten with its charge.
    2. ``get`` per model call: an expired scope is dropped and reads as nothing; a hit becomes
       the most recently used file.

    Worked example, overheads written E (per file) and S (per scope): budget S + 2 × (400 + E),
    three 300-byte files (400 bytes of base64 each) in one scope: put A, put B (held
    S + 2 × (400 + E), full), get A (B is now the least recently used), put C → B is dropped, A
    and C stay, held unchanged.

    Concurrency: every method body runs under one lock and never awaits, so asyncio tasks (and a
    worker thread, should a caller use one) see each ``put``/``get`` as one step.

    Args:
        max_bytes: the most bytes charged at once, across every scope.
        scope_ttl_seconds: how long a scope lives after its first upload.
        clock: a monotonic clock in seconds; tests wind one by hand.
    """

    def __init__(
        self,
        *,
        max_bytes: int,
        scope_ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("the media store's byte budget must be positive")
        if scope_ttl_seconds <= 0:
            raise ValueError("a media store scope's lifetime must be positive")
        self._max_bytes: int = max_bytes
        self._ttl: float = scope_ttl_seconds
        self._clock: Callable[[], float] = clock
        self._lock: threading.Lock = threading.Lock()
        # Least recently used first; `move_to_end` on every hit.
        self._entries: OrderedDict[tuple[BlobScope, str], StoredMedia] = OrderedDict()
        self._digests: dict[BlobScope, set[str]] = {}
        self._expires_at: dict[BlobScope, float] = {}
        self._held: int = 0

    @property
    def held_bytes(self) -> int:
        """The bytes charged right now: every file's base64 and overhead, every scope's overhead."""
        return self._held

    @property
    def max_bytes(self) -> int:
        """The byte budget this store was built with."""
        return self._max_bytes

    @property
    def held_files(self) -> int:
        """How many files are stored right now, across every scope."""
        return len(self._entries)

    @property
    def live_scopes(self) -> int:
        """How many runs' scopes are held right now."""
        return len(self._expires_at)

    def put(self, scope: BlobScope, digest: str, media: StoredMedia) -> None:
        """Store one file under this scope and digest, dropping older files to make room.

        Storing a file the scope already holds replaces it and counts its bytes once.

        Raises:
            MediaOverBudget: the file and a scope record alone are larger than the whole budget.
                Nothing is dropped.
        """
        cost: int = entry_cost(media)
        if cost + SCOPE_OVERHEAD_BYTES > self._max_bytes:
            raise MediaOverBudget(
                f"a file of {len(media.base64_text):,} base64 bytes cannot fit the store's "
                f"budget of {self._max_bytes:,} bytes"
            )
        with self._lock:
            now: float = self._clock()
            self._drop_expired(now)
            # WHY remember the deadline: making room below can drop this scope's last file, and
            # the scope comes back with the deadline it already had, never a later one.
            deadline: float = self._expires_at.get(scope, now + self._ttl)
            key: tuple[BlobScope, str] = (scope, digest)
            if key in self._entries:
                self._forget(key, keep_empty_scope=True)
            while self._held + cost + self._scope_charge(scope) > self._max_bytes and self._entries:
                oldest: tuple[BlobScope, str] = next(iter(self._entries))
                self._forget(oldest)
            if scope not in self._expires_at:
                self._digests[scope] = set()
                self._expires_at[scope] = deadline
                self._held += SCOPE_OVERHEAD_BYTES
            self._entries[key] = media
            self._digests[scope].add(digest)
            self._held += cost

    def get(self, scope: BlobScope | None, digest: str) -> StoredMedia | None:
        """The file stored under exactly this scope and digest, or ``None``.

        ``None`` for: no scope (no token sent), another run's or caller's scope, an expired
        scope, a file dropped for room, or one never uploaded. The caller cannot tell these
        apart, on purpose: each one means "upload again".
        """
        if scope is None:
            return None
        with self._lock:
            expires_at: float | None = self._expires_at.get(scope)
            if expires_at is None:
                return None
            if self._clock() >= expires_at:
                self._drop_scope(scope)
                return None
            key: tuple[BlobScope, str] = (scope, digest)
            media: StoredMedia | None = self._entries.get(key)
            if media is not None:
                self._entries.move_to_end(key)
            return media

    def _scope_charge(self, scope: BlobScope) -> int:
        """What storing into this scope adds for the scope itself: its overhead if it is new."""
        return 0 if scope in self._expires_at else SCOPE_OVERHEAD_BYTES

    def _drop_expired(self, now: float) -> None:
        """Drop every scope whose run deadline has passed. Caller holds the lock."""
        expired: list[BlobScope] = [s for s, at in self._expires_at.items() if now >= at]
        for scope in expired:
            self._drop_scope(scope)

    def _drop_scope(self, scope: BlobScope) -> None:
        """Forget a scope and every file stored under it. Caller holds the lock."""
        for digest in list(self._digests.get(scope, ())):
            self._forget((scope, digest), keep_empty_scope=True)
        self._release_scope(scope)

    def _forget(self, key: tuple[BlobScope, str], *, keep_empty_scope: bool = False) -> None:
        """Remove one file and give its bytes back; forget its scope too if it was the last one.

        WHY an empty scope is forgotten: its record is memory, and keeping it for the run's whole
        life let fresh-token uploads pile up records the budget never saw (review of #2067). The
        cost: a run whose every file was dropped for room starts a new lifetime when it uploads
        again, which gives it nothing it could not get by sending a new token. Caller holds the
        lock.
        """
        media: StoredMedia = self._entries.pop(key)
        self._held -= entry_cost(media)
        scope, digest = key
        digests: set[str] | None = self._digests.get(scope)
        if digests is not None:
            digests.discard(digest)
            if not digests and not keep_empty_scope:
                self._release_scope(scope)

    def _release_scope(self, scope: BlobScope) -> None:
        """Forget a scope's record and give its overhead back. Caller holds the lock."""
        self._digests.pop(scope, None)
        if self._expires_at.pop(scope, None) is not None:
            self._held -= SCOPE_OVERHEAD_BYTES


__all__ = [
    "ENTRY_OVERHEAD_BYTES",
    "SCOPE_OVERHEAD_BYTES",
    "BlobScope",
    "MediaLookup",
    "MediaOverBudget",
    "MediaStore",
    "StoredMedia",
    "entry_cost",
]
