"""Response models of the D18 successor `/v1/admin/accounts/{account_id}/connections` (OME-1497).

# FEATURE: OME-1138 D18 (contract §3, §4) — the neutral Connection DTO the Admin console generates
# its types from. A separate module from `admin_schemas`: the legacy Profile models stay
# byte-identical and retire with OME-1209; these are the successor.
# INVARIANT: no name, id, selector, defaults, locator, generation or key is a field here.
# `masked_key_hint` is always null in the first landing and stays nullable (§3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .profile_models import AuthType


class AdminConnectionOut(BaseModel):
    """The one credential of an `(account, provider)` pair."""

    provider: str
    auth_type: AuthType
    credential_state: Literal["active", "pending", "error"]
    masked_key_hint: str | None = None
    last_refreshed_at: datetime | None = None


class AdminConnectionConflictOut(BaseModel):
    """A provider whose credential cannot be addressed or managed safely (§4)."""

    provider: str
    code: Literal["credential_pair_ambiguous", "credential_pair_unresolved"]
    message: str


class AdminConnectionList(BaseModel):
    connections: list[AdminConnectionOut]
    conflicts: list[AdminConnectionConflictOut]
