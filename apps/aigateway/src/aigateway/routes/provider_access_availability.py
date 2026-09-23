"""`GET /v1/provider-access` — the caller-scoped provider availability listing (OME-1244, A4).

# FEATURE: the backing-neutral successor to a client aggregating `GET /v1/auth/profiles`: one
# read-only listing, per caller, of which registered providers can be dispatched through and how
# far along each one is. The Hosted Engine moves onto it at OME-1245.
# INVARIANT (D17, spec §3.3 op 6): rows carry `provider` and `status` ONLY — no name, id, label,
# default, auth method, account label, locator, reauth URL, credential name or secret-derived
# field — and the route delegates to the provider-access port: no secret read, no refresh, no
# mutation, no credential strategy. Inbound `X-Profile` selects nothing here and is never read.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from ..core.auth.middleware import CurrentAccount
from ..core.provider_access import AvailabilityStatus, provider_access_for

router = APIRouter()


class ProviderAccessAvailabilityRow(BaseModel):
    """One registered provider and the caller's standing with it."""

    # INVARIANT: the closed status family IS the schema. `status` is the `AvailabilityStatus`
    # literal, so an internal value outside it fails validation and never reaches the wire, and a
    # later backing that widens the port's row still publishes these two fields only.
    model_config = ConfigDict(extra="forbid")

    provider: str
    status: AvailabilityStatus


class ProviderAccessAvailability(BaseModel):
    """The listing body: `{"providers": [{"provider": ..., "status": ...}]}`."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderAccessAvailabilityRow]


# WHY no `Vary`: `no-store` already forbids every cache from keeping the body, and `X-Profile`
# must not be named because it selects nothing on this route.
_PRIVATE_CACHE_HEADERS: dict[str, str] = {"Cache-Control": "private, no-store"}


@router.get("/v1/provider-access", response_model=ProviderAccessAvailability)
async def list_provider_access(
    request: Request, response: Response, current: CurrentAccount
) -> ProviderAccessAvailability:
    """List, for the signed-in caller, each registered provider and whether it can be used.

    `status` is one of `not_connected`, `pending`, `connected`, `needs_reauth` or `error`; a row
    carries nothing else. The listing is private to the caller and never cached. The `X-Profile`
    header is ignored: the listing is per caller, not per selection.
    """
    rows = await provider_access_for(request.app).availability(str(current.id))
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    return ProviderAccessAvailability(
        providers=[
            ProviderAccessAvailabilityRow(provider=row.provider, status=row.status) for row in rows
        ]
    )


__all__ = ["router"]
