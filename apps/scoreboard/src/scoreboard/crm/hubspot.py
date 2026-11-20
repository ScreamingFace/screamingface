"""HubSpot adapter for the CRM port: CRM v3 objects and v4 associations over `httpx`.

FEATURE: OME-1504. Authenticated with the "ScreamingFace Leaderboard sync" private app token
(contacts and deals read/write), which reaches the job's pod from Key Vault and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from .decisions import (
    PROP_COUNT,
    PROP_ENTRY,
    PROP_LAST_ACTIVE,
    PROP_SOTA,
    PROP_SOTA_ENTRY,
    PROP_STAGE,
    UNKNOWN_NAME,
    CardState,
)
from .port import Contact, CrmAuthFailed, CrmError, CrmRateLimited

API_BASE_URL = "https://api.hubapi.com"

# INVARIANT (Bennett's rule): a property whose latest value came from one of these sources was set
# by a person, and the sync never overwrites it. Everything else (this app, workflows, imports)
# may be updated.
# AIDEV-NOTE: confirm on the dummy record that this app's own writes do NOT show as one of these
# (spec question 5) before switching prod on.
HAND_SOURCES = frozenset({"CRM_UI", "MOBILE_IOS", "MOBILE_ANDROID"})

# WHY these: the card fields `card_changes` compares, plus the two that place it.
_CARD_PROPERTIES = ("pipeline", PROP_STAGE, PROP_COUNT, PROP_ENTRY, PROP_SOTA, PROP_SOTA_ENTRY)
_HISTORY_PROPERTIES = (PROP_COUNT, PROP_ENTRY, PROP_SOTA, PROP_SOTA_ENTRY)
# HubSpot's documented association type for deal → contact.
_DEAL_TO_CONTACT = 3
_BATCH_LIMIT = 100


def build_client(token: str, *, timeout: float = 20.0) -> httpx.AsyncClient:
    # INVARIANT: the token lives only in this header; it is never logged or stored.
    return httpx.AsyncClient(
        base_url=API_BASE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )


def _contact(payload: Mapping[str, Any]) -> Contact:
    properties = payload.get("properties") or {}
    raw_day = properties.get(PROP_LAST_ACTIVE)
    return Contact(
        id=str(payload["id"]),
        first_name=properties.get("firstname"),
        last_name=properties.get("lastname"),
        # WHY [:10]: a date property reads back as "YYYY-MM-DD", and some API paths return it as
        # a midnight timestamp; the day is what both mean.
        last_active=date.fromisoformat(raw_day[:10]) if raw_day else None,
    )


def _hand_set(history: Mapping[str, Any]) -> frozenset[str]:
    # WHY the first entry: HubSpot lists a property's history newest first.
    return frozenset(
        prop
        for prop, entries in history.items()
        if entries and entries[0].get("sourceType") in HAND_SOURCES
    )


class HubSpotSink:
    """`CrmSink` over HubSpot's API, limited to one deal pipeline (😱 SOTA)."""

    def __init__(self, client: httpx.AsyncClient, *, pipeline_id: str) -> None:
        self._client = client
        self._pipeline_id = pipeline_id

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: Mapping[str, str] | None = None,
        allow: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, json=json, params=params)
        except httpx.TransportError as exc:
            raise CrmError(None) from exc
        if response.status_code in allow or response.is_success:
            return response
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise CrmRateLimited(response.status_code)
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise CrmAuthFailed(response.status_code)
        raise CrmError(response.status_code)

    async def find_contact(self, email: str) -> Contact | None:
        response = await self._request(
            "GET",
            f"/crm/v3/objects/contacts/{quote(email, safe='')}",
            params={"idProperty": "email", "properties": f"firstname,lastname,{PROP_LAST_ACTIVE}"},
            allow=frozenset({httpx.codes.NOT_FOUND}),
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        return _contact(response.json())

    async def create_contact(self, email: str) -> Contact:
        response = await self._request(
            "POST",
            "/crm/v3/objects/contacts",
            json={"properties": {"email": email, "firstname": UNKNOWN_NAME}},
            allow=frozenset({httpx.codes.CONFLICT}),
        )
        if response.status_code == httpx.codes.CONFLICT:
            # WHY: someone created the contact between our lookup and this call; email is unique
            # in HubSpot, so read theirs instead of making a second one.
            existing = await self.find_contact(email)
            if existing is None:
                raise CrmError(httpx.codes.CONFLICT)
            return existing
        return _contact(response.json())

    async def set_last_active(self, contact_id: str, day: date) -> None:
        await self._request(
            "PATCH",
            f"/crm/v3/objects/contacts/{quote(contact_id, safe='')}",
            json={"properties": {PROP_LAST_ACTIVE: day.isoformat()}},
        )

    async def _deal_ids(self, contact_id: str) -> list[str]:
        ids: list[str] = []
        after: str | None = None
        while True:
            params = {"limit": "500"} | ({"after": after} if after else {})
            response = await self._request(
                "GET",
                f"/crm/v4/objects/contacts/{quote(contact_id, safe='')}/associations/deals",
                params=params,
            )
            payload = response.json()
            ids.extend(str(row["toObjectId"]) for row in payload.get("results", []))
            after = ((payload.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return ids

    async def sota_cards(self, contact_id: str) -> list[CardState]:
        ids = await self._deal_ids(contact_id)
        cards: list[CardState] = []
        for start in range(0, len(ids), _BATCH_LIMIT):
            response = await self._request(
                "POST",
                "/crm/v3/objects/deals/batch/read",
                json={
                    "inputs": [{"id": deal_id} for deal_id in ids[start : start + _BATCH_LIMIT]],
                    "properties": list(_CARD_PROPERTIES),
                    "propertiesWithHistory": list(_HISTORY_PROPERTIES),
                },
            )
            for row in response.json().get("results", []):
                properties = row.get("properties") or {}
                # INVARIANT: only the 😱 SOTA pipeline; a person's grant or fundraising deals are
                # never read as their card.
                if properties.get("pipeline") != self._pipeline_id:
                    continue
                cards.append(
                    CardState(
                        id=str(row["id"]),
                        stage_id=properties.get(PROP_STAGE) or "",
                        values=properties,
                        hand_set=_hand_set(row.get("propertiesWithHistory") or {}),
                    )
                )
        return cards

    async def create_card(self, contact_id: str, properties: Mapping[str, str]) -> str:
        response = await self._request(
            "POST",
            "/crm/v3/objects/deals",
            json={
                "properties": {**properties, "pipeline": self._pipeline_id},
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": _DEAL_TO_CONTACT,
                            }
                        ],
                    }
                ],
            },
        )
        return str(response.json()["id"])

    async def update_card(self, card_id: str, properties: Mapping[str, str]) -> None:
        if not properties:
            return
        await self._request(
            "PATCH",
            f"/crm/v3/objects/deals/{quote(card_id, safe='')}",
            json={"properties": dict(properties)},
        )
