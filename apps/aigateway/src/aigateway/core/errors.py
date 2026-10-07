from __future__ import annotations

import json


class AigwError(Exception):
    """Base for every error raised by aigateway."""


class CredentialNotFoundError(AigwError):
    """No credential found in the OS store. User must run the provider's login flow."""


class AuthError(AigwError):
    """Credential present but unusable (malformed / refresh failed / scope rejected)."""


class RefreshSuperseded(AigwError):
    """A refreshed token was not published: the pair's owner or generation moved during the fetch.

    # INVARIANT (OME-1497, G0 §5.3): deliberately NOT an `AuthError` — every caller marks a row
    # errored on `AuthError`, and a refresh that lost a race to an ownership change says nothing
    # about the credential the new owner now holds. Callers answer the superseded conflict.
    """


class ReauthRequiredError(AuthError):
    """Refresh token rejected by the provider — the user must re-authenticate.

    Subclasses AuthError so existing ``except AuthError`` handlers keep working,
    while callers that care can distinguish a permanent rejection (re-auth) from
    a transient refresh failure (retry later).
    """


def is_reauth_refresh_failure(status_code: int, body: str) -> bool:
    """True when a token-refresh failure means the refresh token is dead.

    A 401, or a 400 carrying ``error == "invalid_grant"`` (the OAuth2 code for a
    revoked/expired refresh token), means re-authentication is required.
    Everything else (network errors, provider 5xx) is treated as transient.
    """
    if status_code == 401:
        return True
    if status_code == 400:
        try:
            return json.loads(body).get("error") == "invalid_grant"
        except (ValueError, AttributeError):
            return False
    return False


class ProfileNotFoundError(AigwError):
    """No profile found for the given (provider, name)."""


class ProfilePendingAuthError(AigwError):
    """Profile exists but is still in 'pending' state — auth not complete."""


class BootstrapError(AigwError):
    """Failed to bootstrap the gateway profile index from provider credentials."""
