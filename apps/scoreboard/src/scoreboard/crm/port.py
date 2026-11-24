"""The CRM port the HubSpot sync depends on; adapters implement it.

FEATURE: OME-1504. The job (`scoreboard.hubspot_sync`) talks only to `CrmSink`; the HubSpot adapter
and the dry-run wrapper implement it, so the job is tested with a fake and never imports HTTP code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .decisions import CardState


@dataclass(frozen=True)
class Contact:
    id: str
    first_name: str | None
    last_name: str | None
    last_active: date | None


class CrmError(Exception):
    """A CRM call failed; the submitter's rows are retried later with backoff.

    INVARIANT: the message is a short code (`hubspot_<status>`), never a response body, which
    could echo an email or other request data into logs and the sync table.
    """

    def __init__(self, status: int | None) -> None:
        self.status = status
        super().__init__("hubspot_unreachable" if status is None else f"hubspot_{status}")


class CrmRateLimited(CrmError):
    """429: stop this run and leave the rest for the next one, without counting an attempt."""


class CrmAuthFailed(CrmError):
    """401/403: the token is wrong or lost a scope; no submitter can succeed, so the run stops."""


class CrmSink(Protocol):
    async def find_contact(self, email: str) -> Contact | None: ...

    async def create_contact(self, email: str) -> Contact: ...

    async def set_last_active(self, contact_id: str, day: date) -> None: ...

    async def sota_cards(self, contact_id: str) -> list[CardState]: ...

    async def create_card(self, contact_id: str, properties: Mapping[str, str]) -> str: ...

    async def update_card(self, card_id: str, properties: Mapping[str, str]) -> None: ...
