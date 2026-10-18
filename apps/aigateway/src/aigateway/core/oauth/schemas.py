from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from ..auth_types import AuthType
from .identity import AccountIdentity

OAuthConnectionStatus = Literal["pending", "active", "expired", "revoked", "error"]
OAuthConnectionLabel = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_. @-]+$"),
]


class OAuthConnectionResponse(BaseModel):
    id: UUID
    account_id: UUID
    provider: str
    label: str
    status: OAuthConnectionStatus
    auth_type: AuthType = "oauth"
    account: AccountIdentity | None = None
    credential_locator: dict[str, Any]
    created_at: datetime
    last_used_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    error_message: str | None = None
    is_duplicate: bool = False


class OAuthConnectionListResponse(BaseModel):
    connections: list[OAuthConnectionResponse] = Field(default_factory=list)


class CreateOAuthConnectionRequest(BaseModel):
    provider: str
    label: OAuthConnectionLabel | None = None
    redirect_uri: str | None = None


class PatchOAuthConnectionRequest(BaseModel):
    label: OAuthConnectionLabel | None = None


class CreateApiKeyConnectionRequest(BaseModel):
    """Create an api-key-authenticated connection (no OAuth round-trip)."""

    model_config = ConfigDict(hide_input_in_errors=True)

    provider: str
    label: OAuthConnectionLabel | None = None
    api_key: SecretStr


class SetConnectionApiKeyRequest(BaseModel):
    """Replace the stored API key on an existing api-key connection."""

    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr


class ValidateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: str
    api_key: SecretStr


class ApiKeyValidationResponse(BaseModel):
    provider: str
    state: ApiKeyValidationState
    message: str
    retryable: bool
    stage: ApiKeyValidationStage | None = None
    retry_after_seconds: int | None = None
    probe_model: str | None = None


class OAuthConnectionTokenResponse(BaseModel):
    """Short-lived access token + expiry for an active OAuth connection.

    Returned by GET /v1/oauth/connections/{id}/token for SF backend plugins
    that consume aigateway-managed tokens instead of reading provider CLI
    credential stores directly.
    """

    access_token: str
    expires_at: datetime


class StartOAuthConnectionResponse(BaseModel):
    connection_id: UUID
    authorize_url: str
    state: str
    expires_in: int = 600
