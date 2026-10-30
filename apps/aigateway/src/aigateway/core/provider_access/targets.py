"""The credential targets the Connection-backed authority answers (OME-1209, Stage E, E4a).

Moved from the deleted Profile-backed implementation: a Connection's target, the targetless
answer, and the context stamp the contract endpoint folds into its ids.
"""

from __future__ import annotations

from typing import Any

from ..oauth.models import OAuthConnection
from ..plugin_base import credential_service_provider_for
from .auth_mode import auth_type_of, credentialless_auth_mode
from .connection_locator import credential_name_from_locator
from .profile_authorize import reauth_url_for
from .types import CredentialTarget, TargetKind


def context_stamp(account_id: str, connection: OAuthConnection | None) -> str:
    """Opaque, NON-secret digest input: account + selected target + its state.

    Folded by the contract endpoint into its one-way digests so the ids change when the
    selected target or its generation/state changes. Never echoed.
    # INVARIANT: byte-identical to `routes/model_parameters.py::_context_identity` at 17048f5d for
    # a Connection and for no target — a changed stamp silently re-keys every published contract.
    """
    if connection is None:
        return f"acct:{account_id}|anon"
    target = f"conn:{connection.id}:{connection.status}:{connection.last_refreshed_at or '-'}"
    return f"acct:{account_id}|{target}"


def connection_target(
    account_id: str, provider: str, connection: OAuthConnection, *, plugin: Any
) -> CredentialTarget:
    auth_type = auth_type_of(connection)
    return CredentialTarget(
        kind="stored",
        auth_type=auth_type,
        # WHY the locator (OME-1208, D-S2a-3): a Connection reads the blob its stored
        # `credential_locator` names. A UUID locator yields exactly today's address; a migrated
        # Connection's locator names the Profile's blob, so the label path can never address an
        # empty UUID slot and mark the pair's effective Connection errored on a stray header.
        credential_name=credential_name_from_locator(
            connection.credential_locator,
            credential_provider=credential_service_provider_for(plugin, provider),
            account_id=account_id,
            connection_id=connection.id,
        ),
        context_stamp=context_stamp(account_id, connection),
        reauth_url=reauth_url_for(auth_type, connection_id=str(connection.id)),
        _backing=connection,
    )


def targetless(account_id: str, plugin: Any) -> CredentialTarget:
    kind: TargetKind = "ambient" if credentialless_auth_mode(plugin) is not None else "none"
    return CredentialTarget(
        kind=kind,
        auth_type="oauth",
        credential_name=None,
        context_stamp=context_stamp(account_id, None),
        reauth_url=None,
        _backing=None,
    )


__all__ = ["connection_target", "context_stamp", "targetless"]
