"""The gateway's in-memory file store: scoped, byte-bounded, least recently used first (OME-1970).

FEATURE: Case files by blob reference (OME-1970, PR 4; decisions 3 and 4).
STORY: as a run, I upload a Case's PDF once and every later model call of mine finds it by its
SHA-256; as any other run, or the Runner pod that executes Benchmark scorer code, I cannot use it
by knowing the SHA-256 alone.
INVARIANT: a file is found only under the exact (caller, run token, digest) it was stored under.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from aigateway.core.media_store import BlobScope, MediaStore, StoredMedia

CALLER_A = "11111111-1111-1111-1111-111111111111"
CALLER_B = "22222222-2222-2222-2222-222222222222"
# Stand-ins for the random per-run token the Engine mints (43 URL-safe characters each).
TOKEN_RUN_1 = "r1" + "a" * 41
TOKEN_RUN_2 = "r2" + "b" * 41


def _media(payload: bytes, media_type: str = "image/png") -> tuple[str, StoredMedia]:
    """One stored file and its digest, built the way the upload route builds it."""
    digest: str = hashlib.sha256(payload).hexdigest()
    media = StoredMedia(
        media_type=media_type,
        size_bytes=len(payload),
        base64_text=base64.b64encode(payload).decode("ascii"),
    )
    return digest, media


class _Clock:
    """A hand-wound monotonic clock, so expiry is asserted without sleeping."""

    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now


def _scope(caller: str, token: str | None) -> BlobScope | None:
    return BlobScope.of(caller, token)


def test_a_stored_file_is_found_under_its_own_scope_and_digest() -> None:
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60)
    digest, media = _media(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None

    store.put(scope, digest, media)

    assert store.get(_scope(CALLER_A, TOKEN_RUN_1), digest) == media


def test_another_runs_token_gets_nothing() -> None:
    # WHY: decision 3 — the gateway trusts X-User-Email from every pod on port 9105, so the
    # same caller identity can belong to two runs; only the run's token tells them apart.
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60)
    digest, media = _media(b"%PDF-1.7 one run's file")
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    store.put(scope, digest, media)

    assert store.get(_scope(CALLER_A, TOKEN_RUN_2), digest) is None


def test_a_digest_with_no_token_gets_nothing() -> None:
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60)
    digest, media = _media(b"%PDF-1.7 one run's file")
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    store.put(scope, digest, media)

    assert _scope(CALLER_A, None) is None
    assert store.get(None, digest) is None


@pytest.mark.parametrize("token", ["", "   "])
def test_an_empty_token_names_no_scope(token: str) -> None:
    # INVARIANT: no scope exists without a token, so "no token" can never be a shared scope.
    assert BlobScope.of(CALLER_A, token) is None


def test_another_caller_with_the_same_token_gets_nothing() -> None:
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60)
    digest, media = _media(b"%PDF-1.7 one run's file")
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    store.put(scope, digest, media)

    assert store.get(_scope(CALLER_B, TOKEN_RUN_1), digest) is None


def test_the_scope_holds_the_tokens_hash_never_the_token() -> None:
    scope = BlobScope.of(CALLER_A, TOKEN_RUN_1)
    assert scope is not None

    assert TOKEN_RUN_1 not in repr(scope)
    assert scope.token_hash == hashlib.sha256(TOKEN_RUN_1.encode("ascii")).hexdigest()


def test_the_least_recently_used_file_is_dropped_first_to_stay_within_the_budget() -> None:
    # Each file is 300 bytes on disk = 400 bytes of base64; the budget holds two of them.
    store = MediaStore(max_bytes=800, scope_ttl_seconds=60)
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    first_digest, first = _media(b"1" * 300)
    second_digest, second = _media(b"2" * 300)
    third_digest, third = _media(b"3" * 300)
    store.put(scope, first_digest, first)
    store.put(scope, second_digest, second)
    # Reading the first file makes the second the least recently used.
    assert store.get(scope, first_digest) == first

    store.put(scope, third_digest, third)

    assert store.get(scope, second_digest) is None
    assert store.get(scope, first_digest) == first
    assert store.get(scope, third_digest) == third
    assert store.held_bytes == 800


def test_storing_the_same_file_again_counts_its_bytes_once() -> None:
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60)
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    digest, media = _media(b"9" * 300)

    store.put(scope, digest, media)
    store.put(scope, digest, media)

    assert store.held_bytes == 400


def test_a_file_larger_than_the_whole_budget_is_refused_and_nothing_is_dropped() -> None:
    store = MediaStore(max_bytes=500, scope_ttl_seconds=60)
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    kept_digest, kept = _media(b"k" * 300)
    store.put(scope, kept_digest, kept)
    big_digest, big = _media(b"b" * 600)

    with pytest.raises(ValueError, match="budget"):
        store.put(scope, big_digest, big)

    assert store.get(scope, kept_digest) == kept
    assert store.held_bytes == 400


def test_a_scope_expires_after_its_lifetime_from_the_first_upload() -> None:
    # WHY from the first upload, not the last read: a run ends at the Engine's run deadline
    # whatever it is doing, so the scope ends then too.
    clock = _Clock()
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60, clock=clock)
    scope = _scope(CALLER_A, TOKEN_RUN_1)
    assert scope is not None
    digest, media = _media(b"%PDF-1.7 file")
    store.put(scope, digest, media)

    clock.now += 59
    assert store.get(scope, digest) == media
    clock.now += 1

    assert store.get(scope, digest) is None
    assert store.held_bytes == 0


def test_an_expired_scope_frees_its_bytes_when_another_file_arrives() -> None:
    clock = _Clock()
    store = MediaStore(max_bytes=10_000, scope_ttl_seconds=60, clock=clock)
    old_scope = _scope(CALLER_A, TOKEN_RUN_1)
    new_scope = _scope(CALLER_A, TOKEN_RUN_2)
    assert old_scope is not None and new_scope is not None
    old_digest, old = _media(b"o" * 300)
    store.put(old_scope, old_digest, old)
    clock.now += 61
    new_digest, new = _media(b"n" * 300)

    store.put(new_scope, new_digest, new)

    assert store.held_bytes == 400


def test_a_new_store_refuses_a_budget_or_lifetime_that_is_not_positive() -> None:
    with pytest.raises(ValueError):
        MediaStore(max_bytes=0, scope_ttl_seconds=60)
    with pytest.raises(ValueError):
        MediaStore(max_bytes=100, scope_ttl_seconds=0)
