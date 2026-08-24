"""Request and response models for the ``/v1/admin`` surface.

WHY these exist when the tenant-facing profile routes get by on bare ``dict``: a TypeScript client
is generated from this app's OpenAPI document, and an untyped object there becomes an untyped
object in the console. Every admin route declares a ``response_model`` so the generated types are
real, and so a field rename breaks the UI's typecheck rather than its runtime.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .profile_models import AuthType, ProfileDefaults, ProfileState


class AdminAccountOut(BaseModel):
    """One tenant, as the console lists it.

    `username` IS the Cloudflare-verified email address — `cloudflare_identity` keys the account on
    it, so there is no separate email field to drift out of step.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    is_active: bool


class AdminAccountList(BaseModel):
    accounts: list[AdminAccountOut]
    total: int
    """Total matching the query BEFORE limit/offset — the console needs it to page."""


class CreateAdminAccountRequest(BaseModel):
    """Provision a tenant ahead of their first request.

    No password field, deliberately. In `cloudflare_headers` mode an account is only ever reachable
    by presenting the verified header, and `account_for_identity` stores an empty hash that cannot
    match any candidate password. Accepting one here would imply a login path that does not exist.
    """

    email: str = Field(min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        """A shape check, deliberately not RFC 5322 validation.

        Cloudflare Access is the validator of record — this gateway only ever sees addresses it
        already verified. What this catches is an operator TYPO, which has a specific and
        otherwise-silent consequence: an account keyed on a string Envoy will never send is an
        account nobody can ever authenticate as, and it is indistinguishable in the console from a
        real one.

        Pulling in `email-validator` for a value we do not own would buy strictness we cannot act
        on. 254 is the RFC 5321 path limit and matches the widened `username` column.
        """
        candidate = value.strip()
        local, separator, domain = candidate.partition("@")
        if not separator or not local or "@" in domain or "." not in domain:
            raise ValueError("must be an email address, as Cloudflare Access verifies it")
        return candidate


class PatchAdminAccountRequest(BaseModel):
    """Both fields optional; omitted means unchanged.

    `is_active=False` is the lockout mechanism — `account_for_identity` returns None for a
    deactivated account, so the next request 401s. There is no delete: it would cascade
    `oauth_connections` and orphan `credential_blobs`, which have no foreign key.
    """

    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class AdminProfileOut(BaseModel):
    """One credential profile belonging to a tenant.

    `account_label` is the MASKED display form (`"API key ····WXYZ"`). The raw key is never present
    in this model — there is no field for it, which is the point.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    provider: str
    name: str
    account_label: str | None = None
    state: ProfileState
    auth_type: AuthType
    defaults: ProfileDefaults
    last_refreshed_at: datetime | None = None


class AdminProfileList(BaseModel):
    profiles: list[AdminProfileOut]


class SetAdminApiKeyRequest(BaseModel):
    """Attach or replace a provider API key on a tenant's profile.

    `hide_input_in_errors` matters here more than anywhere else in the app: without it a validation
    failure echoes the offending value back in the 422 body, which for this model is the API key.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr
    defaults: ProfileDefaults | None = None


class PatchAdminProfileRequest(BaseModel):
    defaults: ProfileDefaults | None = None
    account_label: str | None = None


# --- response-cache admin (OME-952) ---------------------------------------------------------------


class AdminCacheInfoOut(BaseModel):
    """Live state of the global response cache, for the console's cache section.

    ``revisions`` are the constants every cache key embeds; a snapshot manifest that disagrees
    with them would load rows the gateway can never serve, which is why the console shows the
    live values beside the upload form.
    """

    serving: bool
    row_count: int
    revisions: dict[str, str]


class AdminCacheJobOut(BaseModel):
    """One snapshot load attempt, as the console lists and polls it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    state: str
    """``validating`` → ``loading`` → ``merging`` → ``complete`` | ``failed`` | ``refused``."""

    mode: str
    """``merge`` (create-or-replace) or ``replace`` (wholesale contents swap)."""

    actor: str
    created_at: datetime
    finished_at: datetime | None = None
    staged_rows: int | None = None
    live_before: int | None = None
    live_after: int | None = None
    inserted_rows: int | None = None
    """Merge mode only, best-effort: derived from the before/after counts, not row RETURNING."""

    updated_rows: int | None = None
    manifest_present: bool = False
    forced: bool = False
    """A revision mismatch was overridden with ``force`` — visible on the job and the audit line."""

    warnings: list[str] = Field(default_factory=list)
    refusal: str | None = None
    """Machine code naming why a ``refused`` job was refused; see the spec's refusal contract."""

    error: str | None = None


class AdminCacheJobList(BaseModel):
    jobs: list[AdminCacheJobOut]
