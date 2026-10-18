from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .auth_types import AuthType


class ProfileState(str, Enum):  # noqa: UP042 - keep tuple-base for pydantic-v1 compat
    PENDING = "pending"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


class ProfileDefaults(BaseModel):
    """Per-profile fallback values applied when the chat body omits a field."""

    model: str | None = None
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout_seconds: float | None = None
    reasoning_effort: str | None = None  # "low" | "medium" | "high"


class Profile(BaseModel):
    id: str  # f"{account_id}:{provider}:{name}"
    account_id: str = ""
    provider: str
    name: str
    account_label: str | None = None
    scopes: list[str] = Field(default_factory=list)
    last_refreshed_at: datetime | None = None
    state: ProfileState = ProfileState.PENDING
    auth_type: AuthType = "oauth"
    defaults: ProfileDefaults = Field(default_factory=ProfileDefaults)


class ProfileIndex(BaseModel):
    version: int = 1
    profiles: list[Profile] = Field(default_factory=list)
    # WHY: OAuth ownership tokens (profile_id -> monotonic generation) live in the index
    # document so the ownership decision is atomic with the pending->authenticated CAS
    # (OME-307 Blocker 1). INVARIANT: this map is an internal operation nonce store — the
    # ProfileIndex is never returned through the API (only individual Profiles are), so the
    # generation never leaks. Kept as a sibling map (not a Profile field) precisely to avoid
    # exposing it via ``Profile.model_dump``.
    oauth_generations: dict[str, int] = Field(default_factory=dict)
