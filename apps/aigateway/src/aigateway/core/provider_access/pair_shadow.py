"""Row 11 — the legacy OAuth shadow identity proof (OME-1497, G1 part 3; contract §5.1).

# FEATURE: OME-1138 D18 — a legacy OAuth callback on a `none` pair writes the Profile blob and a
# shadow Connection at a different (UUID) locator. PUT and DELETE may treat the two as ONE
# credential only when both OAuth identities exist and are equal (owner decision 2026-10-05).
# INVARIANT: identities are compared, never blobs — the Profile path refreshes and rotates only
# its own address, so a byte comparison is almost always false in steady state.
# INVARIANT: this is the successor's only scoped secret read. The decrypted Profile credential
# stays inside `prove_shadow`: it never reaches a log, an error, an exception chain or the wire.
# No refresh is performed to obtain an identity; LIST never calls this module.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..oauth.models import OAuthConnection
from ..oauth.store import credential_locator_for
from ..plugin_base import credential_service_provider_for
from ..secrets.mixin import SecretDecryptionError
from .pair_admin import PairDisposition, store_reads
from .types import PairNotManageable, WriteConflict


async def prove_shadow(app: Any, plugin: Any, disposition: PairDisposition) -> str:
    """The OAuth identity a row-11 Profile and its shadow Connection share — else unresolved.

    Runs before any transaction: a plugin may need network I/O to read an identity, and that never
    happens under an SQL lock. A missing identity, an unextractable or different one, or an
    undecodable, undecryptable or missing Profile blob keeps the pair unresolved (409, the operator
    path).
    """
    marker, document, connection = disposition.marker, disposition.document, disposition.connection
    provider = marker.provider
    # WHY only `none`: a `migrated` pair with a null reference beside a live row is no legacy
    # login's shadow — it is the "any other combination" of row 11 and stays refused.
    if marker.migration_state != "none" or document is None or connection is None:
        raise PairNotManageable(provider, "unresolved")
    expected = connection.identity_sub
    # WHY oauth only: an api-key row keeps a stale `identity_sub` after `set_auth_type`, and a
    # match against it would make a DELETE remove two distinct credentials.
    if not expected or connection.auth_type != "oauth":
        raise PairNotManageable(provider, "unresolved")
    sub = await _profile_identity(app, plugin, provider, marker.account_id, document.name)
    if sub != expected:
        raise PairNotManageable(provider, "unresolved")
    return expected


async def require_shadow_identity(connection_id: UUID, sub: str, provider: str) -> None:
    """Inside the claim: the shadow Connection is still live and still the proven identity.

    # WHY: a re-auth of the shadow to another account between the proof and the claim must not be
    # adopted — the transaction re-reads `identity_sub` (§5.1 step 3).
    """
    current = (
        await OAuthConnection.filter(id=connection_id)
        .exclude(status="revoked")
        .values_list("identity_sub", flat=True)
    )
    if list(current) != [sub]:
        raise WriteConflict("superseded", subject="connection", provider=provider)


async def _profile_identity(
    app: Any, plugin: Any, provider: str, account_id: str, name: str
) -> str | None:
    """The `sub` the Profile's own credential names, or None when it cannot be read or extracted.

    # INVARIANT: the refusal is decided OUTSIDE every `except` block, so no exception that held
    # the decrypted credential (a codec error keeps its whole input in `args`) becomes the
    # refusal's cause or context, and none reaches a log or the wire.
    """
    locator = credential_locator_for(
        credential_service_provider_for(plugin, provider), account_id, name
    )
    with store_reads():
        try:
            raw = await app.state.credential_store.read(locator["service"], locator["account"])
        except SecretDecryptionError:
            # WHY 409, not the row-1 503: a blob this key cannot open never becomes readable, so
            # "temporarily unavailable" would be false; §5.1 names it unresolved.
            raw = None
    credentials = _decoded(raw)
    if credentials is None:
        return None
    failed = False
    identity: Any = None
    try:
        identity = await plugin.extract_identity(
            credentials, http_client_factory=getattr(app.state, f"{provider}_http_factory", None)
        )
    except Exception:
        # WHY broad: a plugin boundary — §5.1 makes ANY failed extraction the operator path,
        # and an extractor's own bug must not turn into a 500 that carries the token.
        failed = True
    sub = None if failed else getattr(identity, "sub", None)
    return sub if isinstance(sub, str) and sub else None


def _decoded(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


__all__ = ["prove_shadow", "require_shadow_identity"]
