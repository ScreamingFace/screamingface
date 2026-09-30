"""CV-18, CV-19, CV-21: the replay grant verifier, against a fake lookup (no database).

FEATURE: OME-1307 (E14) - the gateway serves a frozen version only to a caller that holds a grant
minted by the scoreboard for that version.
INVARIANT (C6): every refusal has a reason from a closed vocabulary, and a forged token never
reports `audience` or `expired`.
INVARIANT (RP-D1): a cached grant never skips the subject check or the expiry check.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aigateway.config import Settings
from aigateway.core.cache_versions.grant import MAX_GRANT_BYTES, Ed25519ReplayGrantVerifier
from aigateway.core.cache_versions.ports import GrantRejected, VerifiedGrant, VersionHit
from aigateway.routes.chat_replay_stage import replay_caller
from tests.unit.cache_versions.conftest import mint_grant, raw_public_b64

pytestmark = pytest.mark.asyncio

_VID = UUID("11111111-2222-4333-8444-555555555555")
_CALLER = "bruno@x.org"


class FakeLookup:
    """A ``CacheVersionLookup`` over a set of version ids, counting ``version_exists`` calls."""

    def __init__(self, existing: set[UUID]) -> None:
        self.existing = existing
        self.exists_calls = 0

    async def version_exists(self, version_id: UUID) -> bool:
        self.exists_calls += 1
        return version_id in self.existing

    async def find(self, version_id: UUID, key_hash: str) -> VersionHit | None:
        raise AssertionError("the verifier never reads an entry")


class Clock:
    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _verifier(
    key: Ed25519PrivateKey,
    lookup: FakeLookup,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
    **kw: Any,
) -> Ed25519ReplayGrantVerifier:
    return Ed25519ReplayGrantVerifier(
        public_keys={"test-kid": key.public_key()},
        lookup=lookup,
        monotonic=monotonic,
        wall=wall,
        **kw,
    )


def _claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "scoreboard",
        "aud": "aigateway",
        "sub": _CALLER,
        "vid": str(_VID),
        "rid": "res-1",
        "iat": now,
        "exp": now + 43_200,
    }
    claims.update(over)
    return claims


def _sign(key: Ed25519PrivateKey, claims: dict[str, Any], kid: str = "test-kid") -> str:
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


def _unsigned_token(header: dict[str, Any]) -> str:
    """A JWS-shaped string with a chosen header. PyJWT refuses to encode a malformed header."""

    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part(header)}.{part(_claims())}.{base64.urlsafe_b64encode(b'x' * 64).decode()}"


def _without_vid(key: Ed25519PrivateKey, other: Ed25519PrivateKey) -> str:
    claims = _claims()
    del claims["vid"]
    return _sign(key, claims)


# (id, token builder(key, other_key), caller, expected reason)
_REFUSALS: list[Any] = [
    pytest.param(
        lambda key, other: mint_grant(other, sub=_CALLER, vid=_VID),
        _CALLER,
        "signature",
        id="signed-by-another-key",
    ),
    pytest.param(
        lambda key, other: mint_grant(key, sub=_CALLER, vid=_VID, kid="unknown-kid"),
        _CALLER,
        "signature",
        id="unknown-kid",
    ),
    pytest.param(lambda key, other: "not-a-jws", _CALLER, "signature", id="not-a-jws"),
    pytest.param(_without_vid, _CALLER, "signature", id="missing-vid"),
    pytest.param(
        lambda key, other: mint_grant(key, sub=_CALLER, vid=_VID, iss="someone"),
        _CALLER,
        "signature",
        id="wrong-issuer",
    ),
    pytest.param(
        lambda key, other: mint_grant(key, sub=_CALLER, vid=_VID, ttl_s=-61),
        _CALLER,
        "expired",
        id="expired",
    ),
    pytest.param(
        lambda key, other: mint_grant(key, sub=_CALLER, vid=_VID, aud="scoreboard"),
        _CALLER,
        "audience",
        id="audience",
    ),
    pytest.param(
        lambda key, other: mint_grant(key, sub=_CALLER, vid=uuid4()),
        _CALLER,
        "unknown_version",
        id="unknown-version",
    ),
    pytest.param(
        lambda key, other: mint_grant(key, sub="carol@x.org", vid=_VID),
        _CALLER,
        "subject",
        id="subject",
    ),
    pytest.param(
        lambda key, other: _sign(key, _claims(vid="not-a-uuid")),
        _CALLER,
        "signature",
        id="vid-not-a-uuid",
    ),
    pytest.param(
        lambda key, other: _sign(key, _claims(sub=42)),
        _CALLER,
        "signature",
        id="sub-not-a-string",
    ),
    pytest.param(
        lambda key, other: _sign(key, _claims(rid=7)),
        _CALLER,
        "signature",
        id="rid-not-a-string",
    ),
    pytest.param(
        lambda key, other: "x" * (MAX_GRANT_BYTES + 1), _CALLER, "signature", id="oversized"
    ),
    pytest.param(
        # WHY: a header without a `kid` cannot select a key, so it is refused, not defaulted.
        lambda key, other: jwt.encode(_claims(), key, algorithm="EdDSA"),
        _CALLER,
        "signature",
        id="no-kid",
    ),
    pytest.param(
        lambda key, other: _unsigned_token({"alg": "EdDSA", "kid": ["a"]}),
        _CALLER,
        "signature",
        id="kid-not-a-string",
    ),
]


@pytest.mark.parametrize(("build", "caller", "reason"), _REFUSALS)
async def test_invalid_grant_rejects_403_with_closed_reason(
    build: Callable[[Ed25519PrivateKey, Ed25519PrivateKey], str],
    caller: str,
    reason: str,
    grant_key: Ed25519PrivateKey,
) -> None:
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    token = build(grant_key, Ed25519PrivateKey.generate())

    with pytest.raises(GrantRejected) as excinfo:
        await verifier.verify(token, caller=caller)

    assert excinfo.value.reason == reason


async def test_a_forged_token_never_reports_audience_or_expired(
    grant_key: Ed25519PrivateKey,
) -> None:
    # INVARIANT: PyJWT checks the signature before the claims. A forger learns nothing about them.
    other = Ed25519PrivateKey.generate()
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    for forged in (
        mint_grant(other, sub=_CALLER, vid=_VID, aud="scoreboard"),
        mint_grant(other, sub=_CALLER, vid=_VID, ttl_s=-3600),
    ):
        with pytest.raises(GrantRejected) as excinfo:
            await verifier.verify(forged, caller=_CALLER)
        assert excinfo.value.reason == "signature"


async def test_a_valid_grant_returns_its_claims(grant_key: Ed25519PrivateKey) -> None:
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    now = int(time.time())
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID, rid="res-9", now=now)

    grant = await verifier.verify(token, caller=_CALLER)

    assert grant == VerifiedGrant(
        version_id=_VID, result_id="res-9", subject=_CALLER, expires_at=now + 43_200
    )


async def test_a_grant_inside_the_skew_window_is_accepted(grant_key: Ed25519PrivateKey) -> None:
    # WHY: real clock, so the row keeps a wide margin (30 s inside the 60 s leeway). `mint_grant`
    # rounds the issue time down by up to 1 s; a row at the very edge would fail at random.
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID, ttl_s=-30)

    grant = await verifier.verify(token, caller=_CALLER)

    assert grant.version_id == _VID


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` is a fixed instant - the clock PyJWT reads in ``decode``."""

    frozen_at: float = 0.0

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FrozenDatetime:
        return cls.fromtimestamp(cls.frozen_at, tz)


@pytest.mark.parametrize(
    ("ttl_s", "reason"),
    [(-59, None), (-61, "expired")],
    ids=["59s-past-exp-accepted", "61s-past-exp-refused"],
)
async def test_the_skew_window_edge_on_a_frozen_clock(
    grant_key: Ed25519PrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    ttl_s: int,
    reason: str | None,
) -> None:
    # WHY: no real clock. PyJWT (fresh path) and the verifier (`wall`) both read the SAME frozen
    # instant, so the 60 s leeway edge is exact and cannot flake under a loaded runner.
    now = 1_800_000_000
    monkeypatch.setattr(_FrozenDatetime, "frozen_at", float(now))
    monkeypatch.setattr(jwt.api_jwt, "datetime", _FrozenDatetime)
    verifier = _verifier(grant_key, FakeLookup({_VID}), wall=Clock(float(now)))
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID, ttl_s=ttl_s, now=now)

    if reason is None:
        grant = await verifier.verify(token, caller=_CALLER)
        assert grant.expires_at == now + ttl_s
    else:
        with pytest.raises(GrantRejected) as excinfo:
            await verifier.verify(token, caller=_CALLER)
        assert excinfo.value.reason == reason


async def test_subject_compare_ignores_case_and_outer_space(grant_key: Ed25519PrivateKey) -> None:
    # WHY: production identity is the lowercased verified email (D5), so `sub` compares that way.
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    token = mint_grant(grant_key, sub="  Ana@Example.org ", vid=_VID)

    grant = await verifier.verify(token, caller="ana@example.org")

    assert grant.version_id == _VID


# --- CV-19: the subject check is skipped when auth is disabled -----------------------------------


async def test_grant_subject_check_skipped_when_auth_disabled(
    grant_key: Ed25519PrivateKey,
) -> None:
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    token = mint_grant(grant_key, sub="someone-else", vid=_VID)

    grant = await verifier.verify(token, caller=None)

    assert grant.subject == "someone-else"


async def test_replay_caller_is_none_when_auth_disabled() -> None:
    from types import SimpleNamespace

    account: Any = SimpleNamespace(username="admin")

    disabled = Settings(**{"_env_file": None, "AIGW_AUTH_MODE": "disabled"})
    jwt_mode = Settings(**{"_env_file": None, "AIGW_AUTH_MODE": "jwt"})

    assert replay_caller(disabled, account) is None
    assert replay_caller(jwt_mode, account) == "admin"


# --- CV-21: a verified grant is cached for the TTL, and only the lookup is skipped ----------------


async def test_verified_grant_cached_60s(grant_key: Ed25519PrivateKey) -> None:
    lookup = FakeLookup({_VID})
    mono = Clock(1000.0)
    verifier = _verifier(grant_key, lookup, monotonic=mono, wall=Clock(time.time()))
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID)

    await verifier.verify(token, caller=_CALLER)
    mono.now = 1059.0
    await verifier.verify(token, caller=_CALLER)
    assert lookup.exists_calls == 1

    mono.now = 1061.0
    await verifier.verify(token, caller=_CALLER)
    assert lookup.exists_calls == 2

    other = mint_grant(grant_key, sub=_CALLER, vid=_VID, rid="res-2")
    await verifier.verify(other, caller=_CALLER)
    assert lookup.exists_calls == 3, "another token has its own entry"


async def test_a_cached_grant_still_checks_the_subject(grant_key: Ed25519PrivateKey) -> None:
    verifier = _verifier(grant_key, FakeLookup({_VID}))
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID)
    await verifier.verify(token, caller=_CALLER)

    with pytest.raises(GrantRejected) as excinfo:
        await verifier.verify(token, caller="carol@x.org")

    assert excinfo.value.reason == "subject"


async def test_a_cached_grant_past_exp_plus_skew_is_expired(grant_key: Ed25519PrivateKey) -> None:
    lookup = FakeLookup({_VID})
    wall = Clock(float(int(time.time())))
    verifier = _verifier(grant_key, lookup, wall=wall)
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID, ttl_s=100, now=wall.now)
    await verifier.verify(token, caller=_CALLER)

    wall.now += 100 + 60  # exactly exp + leeway: still accepted
    await verifier.verify(token, caller=_CALLER)
    wall.now += 2  # past exp + leeway
    with pytest.raises(GrantRejected) as excinfo:
        await verifier.verify(token, caller=_CALLER)

    assert excinfo.value.reason == "expired"
    assert lookup.exists_calls == 1, "the expiry check reads no store"


async def test_an_expired_entry_is_dropped_from_the_cache(grant_key: Ed25519PrivateKey) -> None:
    lookup = FakeLookup({_VID})
    wall = Clock(float(int(time.time())))
    verifier = _verifier(grant_key, lookup, wall=wall)
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID, ttl_s=100, now=wall.now)
    await verifier.verify(token, caller=_CALLER)
    wall.now += 200
    with pytest.raises(GrantRejected):
        await verifier.verify(token, caller=_CALLER)

    with pytest.raises(GrantRejected):
        await verifier.verify(token, caller=_CALLER)

    # WHY 2: the expired entry was dropped, so the second call ran the full path again (one more
    # lookup) and then failed the expiry check. A kept entry would have answered with no lookup.
    assert lookup.exists_calls == 2


async def test_a_rejection_is_never_cached(grant_key: Ed25519PrivateKey) -> None:
    lookup = FakeLookup(set())
    verifier = _verifier(grant_key, lookup)
    token = mint_grant(grant_key, sub=_CALLER, vid=_VID)
    with pytest.raises(GrantRejected) as excinfo:
        await verifier.verify(token, caller=_CALLER)
    assert excinfo.value.reason == "unknown_version"

    lookup.existing.add(_VID)  # the version now exists (a freeze finished)
    grant = await verifier.verify(token, caller=_CALLER)

    assert grant.version_id == _VID
    assert lookup.exists_calls == 2


async def test_the_cache_drops_the_oldest_entry_at_its_bound(
    grant_key: Ed25519PrivateKey,
) -> None:
    lookup = FakeLookup({_VID})
    mono = Clock(1000.0)
    verifier = _verifier(grant_key, lookup, monotonic=mono, max_cached=2)
    tokens = [mint_grant(grant_key, sub=_CALLER, vid=_VID, rid=f"res-{n}") for n in range(3)]
    for token in tokens:
        await verifier.verify(token, caller=_CALLER)
        mono.now += 1
    assert lookup.exists_calls == 3

    await verifier.verify(tokens[2], caller=_CALLER)  # newest: still cached
    assert lookup.exists_calls == 3
    await verifier.verify(tokens[0], caller=_CALLER)  # oldest: dropped, so looked up again
    assert lookup.exists_calls == 4


# --- from_config: the D7 (X-4) key map format -----------------------------------------------


async def test_from_config_decodes_raw_base64_public_keys(grant_key: Ed25519PrivateKey) -> None:
    verifier = Ed25519ReplayGrantVerifier.from_config(
        {"test-kid": raw_public_b64(grant_key)}, lookup=FakeLookup({_VID})
    )

    grant = await verifier.verify(mint_grant(grant_key, sub=_CALLER, vid=_VID), caller=_CALLER)

    assert grant.version_id == _VID


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("!!!not base64!!!", id="not-base64"),
        pytest.param(base64.b64encode(b"\x01" * 31).decode(), id="31-bytes"),
        pytest.param(base64.b64encode(b"\x01" * 33).decode(), id="33-bytes"),
        pytest.param("", id="empty"),
    ],
)
async def test_from_config_refuses_a_bad_key_and_names_the_kid(value: str) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        Ed25519ReplayGrantVerifier.from_config({"kid-7": value}, lookup=FakeLookup(set()))

    assert str(excinfo.value) == (
        "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS['kid-7'] is not base64 of a 32-byte Ed25519 public key"
    )
    assert value not in str(excinfo.value) or value == ""
