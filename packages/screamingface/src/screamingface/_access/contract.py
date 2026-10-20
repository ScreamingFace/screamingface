"""Cloudflare Access URL, token, and encrypted-transfer primitives."""

from __future__ import annotations

import base64
import json
import math
import re
import threading
import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from nacl.exceptions import CryptoError
from nacl.public import Box, PrivateKey, PublicKey

from screamingface._environment import running_in_notebook as _running_in_notebook
from screamingface.errors import AuthenticationError

_MAX_TRANSFER_BYTES = 1_000_000
_REFRESH_SKEW_SECONDS = 30.0
_VALID_AUDIENCE = re.compile(r"[A-Za-z0-9_-]{16,256}\Z")
# A compact JWS segment: unpadded base64url only. `b64decode(altchars=b"-_")` alone would also
# accept the standard alphabet's `+` and `/`.
_JWS_SEGMENT = re.compile(r"[A-Za-z0-9_-]+\Z")
# Cloudflare Access challenges an unauthenticated caller with a 302 to its login origin, and
# refuses a policy-blocked one with 401/403. It does not challenge with 301/303/307/308, and
# a 2xx is never a challenge — widening this set would add false-positive surface to the very
# check that exists to remove it.
_ACCESS_CHALLENGE_STATUSES = frozenset({302, 401, 403})


def _challenge_audience(status_code: int, headers: Mapping[str, str]) -> str | None:
    """The Access audience from a CHALLENGE response, or None if this is not one.

    Takes the status and headers rather than a response object so that both ``httpx`` and
    ``websockets`` responses reach the same predicate — the two used to disagree, and the
    HTTP side did not check the status at all.
    """

    if status_code not in _ACCESS_CHALLENGE_STATUSES:
        return None
    audience = headers.get("cf-access-aud")
    if audience is None:
        location = headers.get("location")
        if location:
            values = parse_qs(urlsplit(location).query).get("kid", [])
            audience = values[0] if len(values) == 1 else None
    if audience is None:
        return None
    audience = audience.strip()
    return audience if _VALID_AUDIENCE.fullmatch(audience) else None


@dataclass(frozen=True, slots=True, repr=False)
class _AccessToken:
    value: str
    expires_at: float


def _access_audience(response: httpx.Response) -> str | None:
    """The ``httpx``-shaped adapter over :func:`_challenge_audience`."""

    return _challenge_audience(response.status_code, response.headers)


def _raise_if_cancelled(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise _auth_error(
            "Cloudflare Access login was cancelled",
            code="access_login_cancelled",
            permanent=False,
        )


def _access_authorization_url(
    origin: str,
    audience: str,
    public_key: str,
    *,
    redirect_path: str | None = None,
) -> str:
    """Build the browser login URL; ``redirect_path`` (already encoded) replaces the origin path.

    WHY: the edge transfers the application token only on a request that Access gates. An
    application scoped to a path (production `/v1/scores`, OME-1649) leaves the origin root
    public, so the login must end on the path that was challenged, never on `/`.
    """

    parts = urlsplit(origin)
    transfer = {
        "token": public_key,
        "aud": audience,
        "send_org_token": "true",
        "edge_token_transfer": "true",
    }
    path = parts.path if redirect_path is None else redirect_path
    transfer["redirect_url"] = urlunsplit(
        (parts.scheme, parts.netloc, path, urlencode(transfer), "")
    )
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/cdn-cgi/access/cli",
            urlencode(transfer),
            "",
        )
    )


def _access_logout_url(origin: str) -> str:
    parts = urlsplit(origin)
    return urlunsplit((parts.scheme, parts.netloc, "/cdn-cgi/access/logout", "", ""))


def _present_access_authorization(authorization_url: str) -> None:
    print(f"Complete Cloudflare Access login in your browser:\n\n{authorization_url}\n")
    if _running_in_notebook():
        return
    try:
        webbrowser.open(authorization_url, new=2)
    except (OSError, webbrowser.Error):
        # The URL is already visible for terminals without a browser integration.
        return


def _present_access_logout(logout_url: str) -> None:
    print(f"Completing Cloudflare Access logout in your browser:\n\n{logout_url}\n")
    try:
        webbrowser.open(logout_url, new=2)
    except (OSError, webbrowser.Error):
        # The URL is already visible for environments without browser integration.
        return


def _decrypt_transfer(response: httpx.Response, private_key: PrivateKey) -> str:
    if len(response.content) > _MAX_TRANSFER_BYTES:
        raise _invalid_transfer()
    service_key = response.headers.get("service-public-key")
    if not service_key:
        raise _invalid_transfer()
    try:
        peer = PublicKey(_base64url_decode(service_key))
        encrypted = base64.b64decode(response.content, validate=True)
        decrypted = Box(private_key, peer).decrypt(encrypted)
        payload = json.loads(decrypted)
    except (ValueError, TypeError, json.JSONDecodeError, CryptoError) as exc:
        raise _invalid_transfer() from exc
    token = payload.get("app_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise _invalid_transfer()
    return token


def _access_token(value: str, monotonic_now: float, wall_now: float) -> _AccessToken:
    return _token_from_claims(value, _token_claims(value), monotonic_now, wall_now)


def _token_claims(value: str) -> dict[str, object]:
    """The payload claims of a compact JWS, parsed once and strictly.

    The signature is NOT verified here: the Access edge verifies it. This only rejects a value
    that cannot be a compact JWS at all, so a malformed token fails at construction instead of
    being sent and refused later: three segments, a non-empty base64url JSON-object header, a
    base64url JSON-object payload, and a non-empty base64url signature. Non-standard JSON
    constants (NaN, Infinity, -Infinity) are refused.
    """

    parts = value.split(".")
    if len(parts) != 3 or not all(_JWS_SEGMENT.fullmatch(part) for part in parts):
        raise _invalid_token()
    try:
        header = _strict_json(_base64url_decode(parts[0]))
        payload = _strict_json(_base64url_decode(parts[1]))
        _base64url_decode(parts[2])
    except (ValueError, TypeError, RecursionError) as exc:
        # RecursionError: deeply nested JSON exhausts the parser; still a malformed token.
        raise _invalid_token() from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise _invalid_token()
    return payload


def _token_from_claims(
    value: str, claims: Mapping[str, object], monotonic_now: float, wall_now: float
) -> _AccessToken:
    """Check the time claims and pin the expiry to the monotonic clock.

    ``exp`` is required; ``nbf``, when present, must not lie in the future beyond the same
    skew the refresh margin allows (a token minted on a slightly faster clock stays usable).
    """

    expires = _finite_number(claims.get("exp"))
    lifetime = expires - wall_now
    if not math.isfinite(lifetime) or lifetime <= _REFRESH_SKEW_SECONDS:
        raise _invalid_token()
    if "nbf" in claims and _finite_number(claims["nbf"]) > wall_now + _REFRESH_SKEW_SECONDS:
        raise _invalid_token()
    expires_at = monotonic_now + lifetime
    if not math.isfinite(expires_at):
        raise _invalid_token()
    return _AccessToken(value, expires_at)


def _finite_number(claim: object) -> float:
    if not isinstance(claim, int | float) or isinstance(claim, bool):
        raise _invalid_token()
    try:
        number = float(claim)
    except OverflowError as exc:  # an int too large for a float
        raise _invalid_token() from exc
    if not math.isfinite(number):
        raise _invalid_token()
    return number


def _token_audiences(claims: Mapping[str, object]) -> tuple[str, ...]:
    """Every Access audience a token's claims name in ``aud`` (string or list).

    The signature is NOT verified here: the Access edge verifies it. This only decides which
    store slots a caller-supplied token may occupy.
    """

    claim = claims.get("aud")
    values: object = [claim] if isinstance(claim, str) else claim
    if not isinstance(values, list) or not values:
        raise _invalid_token()
    audiences: list[str] = []
    for item in values:
        if not isinstance(item, str) or not _VALID_AUDIENCE.fullmatch(item):
            raise _invalid_token()
        audiences.append(item)
    return tuple(audiences)


def _reject_constant(name: str) -> object:
    raise ValueError(f"non-standard JSON constant {name}")


def _strict_json(raw: bytes) -> object:
    """``json.loads`` that refuses NaN/Infinity/-Infinity (``ValueError``, like bad JSON)."""

    return json.loads(raw, parse_constant=_reject_constant)


def _base64url_padded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(f"{value}{padding}", altchars=b"-_", validate=True)


def _invalid_transfer() -> AuthenticationError:
    return _auth_error(
        "Cloudflare Access returned an invalid encrypted login transfer",
        code="access_invalid_transfer",
    )


def _invalid_token() -> AuthenticationError:
    return _auth_error(
        "Cloudflare Access returned an invalid or expired application token",
        code="access_invalid_token",
    )


def _auth_error(
    message: str,
    *,
    code: str,
    status: int | None = None,
    permanent: bool = True,
) -> AuthenticationError:
    return AuthenticationError(message, code=code, status=status, permanent=permanent)


def _require_positive_timeout(timeout: float) -> None:
    if not isinstance(timeout, int | float) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout must be a positive number")


__all__: list[str] = []
