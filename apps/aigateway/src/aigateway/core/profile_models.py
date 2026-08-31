from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# INVARIANT: AuthType is the PERSISTED credential type — the only values a stored
# Profile or OAuthConnection may hold, and the only ones a credential strategy can
# be built for. AuthMode is the RESOLVED outcome, which additionally admits "none"
# for a provider that needs no upstream credential at all (OME-636).
#
# WHY two literals instead of widening one: "none" must be unforgeable. Keeping it
# out of AuthType means no persisted model and no request schema ever accepts it,
# so a client cannot declare it and an operator cannot store it — enforced by the
# type checker rather than by a validation rule someone can forget to write.
# AIDEV-NOTE: "none" means no PROVIDER credential. It says nothing about the
# caller's own authentication to AIGateway, which is unchanged.
AuthType = Literal["oauth", "api_key"]
AuthMode = Literal["oauth", "api_key", "none"]


def profile_id_for(account_id: str, provider: str, name: str) -> str:
    return f"{account_id}:{provider}:{name}"


def credential_name_for(account_id: str, name: str) -> str:
    return f"{account_id}:{name}"


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
    # OME-1026 F3: profile_id -> monotonic CREDENTIAL generation, bumped inside the same
    # atomic index CAS that publishes a credential. Distinct from oauth_generations, which
    # is an OAuth *flow ownership* nonce with its own CAS semantics; overloading that map
    # would make a credential change look like a superseded OAuth flow.
    # INVARIANT: this is the private model cache's identity fence. A wall-clock stamp could
    # repeat within one tick, letting a replaced key inherit the previous key's cache
    # identity. Being durable AND advancing inside the CAS makes it collision-free across
    # workers and across restarts.
    # INVARIANT: same reason as oauth_generations for living here rather than on Profile —
    # ProfileIndex is never returned by the API, so the generation cannot leak through
    # ``Profile.model_dump``.
    credential_generations: dict[str, int] = Field(default_factory=dict)
