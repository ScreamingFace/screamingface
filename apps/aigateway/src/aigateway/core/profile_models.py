from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# WHY the module, not the name: `from .auth_types import AuthType` would make
# `profile_models.AuthType` importable again, a second home E4/E5 would have to keep (OME-1209 E2a).
from . import auth_types


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
    auth_type: auth_types.AuthType = "oauth"
    defaults: ProfileDefaults = Field(default_factory=ProfileDefaults)


class ProfileIndex(BaseModel):
    version: int = 1
    profiles: list[Profile] = Field(default_factory=list)
