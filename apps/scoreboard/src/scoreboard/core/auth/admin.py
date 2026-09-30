"""Who may take a publication down: the admin allowlist decision, pure.

FEATURE: OME-1307 (E14). Mirrors `apps/aigateway/src/aigateway/core/auth/admin.py`, but only the
pure part: the `require_admin` dependency raises `HTTPException`, so it lives in
`scoreboard.routes.admin`.

INVARIANT: standard library only. WHY no FastAPI here: `core/auth/` is pure
(`cloudflare_identity.py` imports only the standard library), and the layering guard (PB-20a)
bans `fastapi` in `core/`.

INVARIANT: an admin is not a tenant. Nothing here writes to the database, and an admin address
grants no account.
"""

from __future__ import annotations

from dataclasses import dataclass


def email_is_admin(email: str, admin_emails: frozenset[str]) -> bool:
    """Whether `email` is on the allowlist.

    Lowercased on both sides: `Settings._parse_admin_emails` lowercases the allowlist, and this
    lowercases the candidate, because mail domains are case-insensitive and an operator will
    eventually type a capital on one side only. An empty allowlist admits nobody.
    """
    return email.strip().lower() in admin_emails


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    """One administrator, as Cloudflare verified them. Not an account: no id, no row."""

    email: str
