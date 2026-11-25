"""A `CrmSink` that reads through to HubSpot and only logs what it would write.

FEATURE: OME-1504 — the history check before prod is switched on (decision 2026-11-18): run
`python -m scoreboard.hubspot_sync --dry-run` and review every change before any is sent.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date

from .decisions import CardState
from .port import Contact, CrmSink

logger = logging.getLogger(__name__)

# WHY: a contact the dry run would create does not exist, so it has no cards to read.
_WOULD_CREATE = "dry-run-new-contact"


class DryRunSink:
    def __init__(self, inner: CrmSink) -> None:
        self._inner = inner

    async def find_contact(self, email: str) -> Contact | None:
        return await self._inner.find_contact(email)

    async def create_contact(self, email: str) -> Contact:
        # INVARIANT: the email is not logged; pod logs are not the place for submitters' addresses.
        logger.info("dry run: would create a contact")
        return Contact(id=_WOULD_CREATE, first_name=None, last_name=None, last_active=None)

    async def set_last_active(self, contact_id: str, day: date) -> None:
        logger.info("dry run: contact %s last active %s", contact_id, day.isoformat())

    async def sota_cards(self, contact_id: str) -> list[CardState]:
        if contact_id == _WOULD_CREATE:
            return []
        return await self._inner.sota_cards(contact_id)

    async def create_card(self, contact_id: str, properties: Mapping[str, str]) -> str:
        shown = {key: value for key, value in properties.items() if key != "dealname"}
        logger.info("dry run: would create a card for contact %s: %s", contact_id, shown)
        return "dry-run-new-card"

    async def update_card(self, card_id: str, properties: Mapping[str, str]) -> None:
        logger.info("dry run: card %s changes %s", card_id, dict(properties) or "nothing")
