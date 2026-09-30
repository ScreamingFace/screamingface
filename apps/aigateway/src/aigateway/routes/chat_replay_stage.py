"""STAGE 0 of the chat route: replay from a frozen cache version (OME-1307, GW-replay).

FEATURE: OME-1307 (E14) - a call that carries ``X-AIGW-Cache-Replay`` is checked against the grant
and then looked up in the frozen version, before the live global cache and before any credential.

INVARIANT (CV-E4): an invalid grant is a ``403 replay_grant_invalid`` and NEVER falls through to
the live path. A gateway that cannot verify a grant refuses it too (OD-R1), so a replay run never
becomes a silent paid run.
INVARIANT: the version is never an availability dependency. A lookup error is a miss with a
WARNING, and the miss header keeps it visible to the engine.
INVARIANT: the blob body is model output. It is returned as data and never parsed or acted on
(CV-D10). No log line carries a token, a prompt or a response: key and token prefixes only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from fastapi import HTTPException, Request

from ..config import Settings
from ..core.auth.models import BaseAccount
from ..core.cache_versions import (
    CaptureKey,
    GrantRejected,
    VersionHit,
    build_capture_key,
)
from ..core.plugin_base import ProviderPluginBase
from .chat_cache_stage import CACHE_HEADER, KEY_HEADER, KEY_PREFIX_LENGTH, REASON_HEADER

logger = logging.getLogger(__name__)

REPLAY_REQUEST_HEADER: Final = "X-AIGW-Cache-Replay"
VERSION_HEADER: Final = "X-AIGW-Cache-Version"
CACHE_STATUS_HEADER: Final = "Cache-Status"
VERSION_HIT_CACHE_STATUS_PREFIX: Final = "aigateway; hit; detail=version"


def version_hit_cache_status(key_hash: str) -> str:
    return f'{VERSION_HIT_CACHE_STATUS_PREFIX}; key="{key_hash[:KEY_PREFIX_LENGTH]}"'


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    status: Literal["hit", "miss"]
    key_hash: str | None
    hit: VersionHit | None


def replay_caller(settings: Settings, account: BaseAccount) -> str | None:
    """The identity a grant subject must equal, or ``None`` when auth is disabled (RP-D8).

    WHY the username: in production (D5) the mode is ``cloudflare_headers`` and the username is
    the lowercased verified ``X-User-Email``. The scoreboard puts the same verified email in the
    grant ``sub``. ``disabled`` is a dev/local fallback only.
    """
    if settings.auth_mode == "disabled":
        return None
    return account.username


async def resolve_replay(
    request: Request,
    *,
    caller: str | None,
    body: dict[str, Any],
    plugin: ProviderPluginBase,
    capture_key: CaptureKey | None,
) -> ReplayOutcome | None:
    token = (request.headers.get(REPLAY_REQUEST_HEADER) or "").strip()
    if not token:
        return None
    state = request.app.state
    verifier = state.replay_grant_verifier
    if not state.settings.cache_versions_enabled or verifier is None:
        # OD-R1: this gateway holds no key that verifies the grant. Refuse; never run it live.
        raise _refusal("signature", state)
    try:
        grant = await verifier.verify(token, caller=caller)
    except GrantRejected as exc:
        raise _refusal(exc.reason, state) from None
    key = capture_key or build_capture_key(body=body, plugin=plugin)
    hit = await _find(state, grant.version_id, key)
    outcome = "hit" if hit is not None else "miss"
    state.capture_stats.replay_lookups[outcome] += 1
    return ReplayOutcome(
        status=outcome, key_hash=key.key_hash if key is not None else None, hit=hit
    )


async def _find(state: Any, version_id: UUID, key: CaptureKey | None) -> VersionHit | None:
    """The version's answer for ``key``. A key-less call, or a lookup error, is a miss."""
    if key is None:
        return None
    try:
        return await state.cache_version_lookup.find(version_id, key.key_hash)
    except Exception as exc:
        # The exception TYPE only: its text can carry SQL parameters, i.e. the prompt.
        logger.warning(
            "cache version lookup failed (%s) key=%s…",
            type(exc).__name__,
            key.key_hash[:KEY_PREFIX_LENGTH],
        )
        return None


def _refusal(reason: str, state: Any) -> HTTPException:
    state.capture_stats.replay_lookups["invalid_grant"] += 1
    return HTTPException(
        status_code=403,
        detail={
            "code": "replay_grant_invalid",
            "reason": reason,
            "message": "the cache replay grant was refused",
        },
    )


def replay_headers(outcome: ReplayOutcome | None) -> dict[str, str]:
    """The response headers of a replay call. ``{}`` for a call that carried no grant.

    INVARIANT (ENG-replay C12): every 2xx answer to a call with a valid grant carries
    ``X-AIGW-Cache-Version: hit|miss``. The engine counts a missing header as a version miss.
    """
    if outcome is None:
        return {}
    if outcome.hit is None or outcome.key_hash is None:
        return {VERSION_HEADER: "miss"}
    return {
        VERSION_HEADER: "hit",
        CACHE_STATUS_HEADER: version_hit_cache_status(outcome.key_hash),
        CACHE_HEADER: "hit",
        REASON_HEADER: "",
        KEY_HEADER: outcome.key_hash[:KEY_PREFIX_LENGTH],
    }
