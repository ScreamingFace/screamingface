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

from pydantic import BaseModel, ConfigDict, SecretStr

from .auth_types import AuthType


class AdminConnectionOut(BaseModel):
    """The one credential of an `(account, provider)` pair."""

    provider: str
    auth_type: AuthType
    credential_state: Literal["active", "pending", "error"]
    masked_key_hint: str | None
    last_refreshed_at: datetime | None


class AdminConnectionConflictOut(BaseModel):
    """A provider whose credential cannot be addressed or managed safely (§4)."""

    provider: str
    code: Literal["credential_pair_ambiguous", "credential_pair_unresolved"]
    message: str


class AdminConnectionList(BaseModel):
    connections: list[AdminConnectionOut]
    conflicts: list[AdminConnectionConflictOut]


# NOTE: published in OpenAPI only. The route reads the raw body in an auth-dependent
# dependency (§6.1) so authentication runs before JSON parsing and every refusal is the secret-safe
# successor 422 — a validation error built from this model would echo input. A docstring here
# becomes the public OpenAPI `description`, so internal notes stay in comments.
class SetAdminConnectionApiKeyRequest(BaseModel):
    """The one API key to attach to the provider."""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr
