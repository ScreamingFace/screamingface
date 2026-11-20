"""The HubSpot adapter sends the requests the sync means, and maps HubSpot's errors (OME-1504).

FEATURE: the sync talks to HubSpot's CRM API (v3 objects, v4 associations) with a private app
token. These tests pin the request shapes against a mock transport; nothing reaches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import httpx
import pytest

from scoreboard.crm.decisions import PROP_COUNT, PROP_ENTRY, PROP_SOTA, PROP_STAGE
from scoreboard.crm.hubspot import HubSpotSink
from scoreboard.crm.port import CrmAuthFailed, CrmError, CrmRateLimited

pytestmark = pytest.mark.asyncio

PIPELINE = "941434182"
TOKEN = "pat-secret-token"
APP_ID = "62476090"


class _Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def _sink(
    respond: Callable[[httpx.Request], httpx.Response], *, app_id: str | None = APP_ID
) -> tuple[HubSpotSink, _Recorder]:
    recorder = _Recorder(respond)
    client = httpx.AsyncClient(
        base_url="https://api.hubapi.com",
        transport=httpx.MockTransport(recorder),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    return HubSpotSink(client, pipeline_id=PIPELINE, app_id=app_id), recorder


def _body(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)


async def test_find_contact_by_email_reads_name_and_last_active() -> None:
    sink, recorder = _sink(
        lambda _: httpx.Response(
            200,
            json={
                "id": "501",
                "properties": {
                    "firstname": "Ana",
                    "lastname": None,
                    "sf_last_active_date": "2026-11-09",
                },
            },
        )
    )
    contact = await sink.find_contact("ana+lab@uni.edu")

    assert contact is not None
    assert (contact.id, contact.first_name, contact.last_name, contact.last_active) == (
        "501",
        "Ana",
        None,
        date(2026, 11, 9),
    )
    [request] = recorder.requests
    assert request.method == "GET"
    assert request.url.path == "/crm/v3/objects/contacts/ana+lab@uni.edu"
    assert request.url.params["idProperty"] == "email"


async def test_an_unknown_email_is_no_contact() -> None:
    sink, _ = _sink(lambda _: httpx.Response(404, json={"status": "error"}))
    assert await sink.find_contact("nobody@uni.edu") is None


async def test_create_contact_sends_the_email_and_the_unknown_name() -> None:
    sink, recorder = _sink(lambda _: httpx.Response(201, json={"id": "777", "properties": {}}))
    contact = await sink.create_contact("ana@uni.edu")

    assert contact.id == "777"
    [request] = recorder.requests
    assert (request.method, request.url.path) == ("POST", "/crm/v3/objects/contacts")
    assert _body(request) == {"properties": {"email": "ana@uni.edu", "firstname": "Unknown"}}


async def test_a_contact_created_meanwhile_is_read_back_instead_of_duplicated() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={"category": "CONFLICT"})
        return httpx.Response(200, json={"id": "888", "properties": {"firstname": "Ana"}})

    sink, recorder = _sink(respond)
    contact = await sink.create_contact("ana@uni.edu")

    assert contact.id == "888"
    assert [r.method for r in recorder.requests] == ["POST", "GET"]


async def test_set_last_active_writes_a_date() -> None:
    sink, recorder = _sink(lambda _: httpx.Response(200, json={"id": "501"}))
    await sink.set_last_active("501", date(2026, 11, 9))

    [request] = recorder.requests
    assert (request.method, request.url.path) == ("PATCH", "/crm/v3/objects/contacts/501")
    assert _body(request) == {"properties": {"sf_last_active_date": "2026-11-09"}}


async def test_sota_cards_keeps_only_this_pipeline_and_marks_hand_typed_values() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/crm/v4/"):
            return httpx.Response(200, json={"results": [{"toObjectId": 11}, {"toObjectId": 12}]})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "11",
                        "properties": {
                            "pipeline": PIPELINE,
                            PROP_STAGE: "1450673810",
                            PROP_COUNT: "1",
                            PROP_ENTRY: "typed by hand",
                        },
                        "propertiesWithHistory": {
                            PROP_ENTRY: [{"value": "typed by hand", "sourceType": "CRM_UI"}],
                            PROP_COUNT: [
                                {
                                    "value": "1",
                                    "sourceType": "INTEGRATION",
                                    "sourceId": APP_ID,
                                    "timestamp": "2026-11-20T10:00:00Z",
                                }
                            ],
                        },
                    },
                    {
                        "id": "12",
                        "properties": {"pipeline": "68526621", PROP_STAGE: "x"},
                        "propertiesWithHistory": {},
                    },
                ]
            },
        )

    sink, recorder = _sink(respond)
    [card] = await sink.sota_cards("501")

    assert (card.id, card.stage_id) == ("11", "1450673810")
    assert card.values[PROP_COUNT] == "1"
    assert card.protected == frozenset({PROP_ENTRY})
    association, batch = recorder.requests
    assert association.url.path == "/crm/v4/objects/contacts/501/associations/deals"
    assert batch.url.path == "/crm/v3/objects/deals/batch/read"
    assert _body(batch)["inputs"] == [{"id": "11"}, {"id": "12"}]


async def test_a_contact_without_deals_has_no_cards_and_needs_no_batch_read() -> None:
    sink, recorder = _sink(lambda _: httpx.Response(200, json={"results": []}))
    assert await sink.sota_cards("501") == []
    assert len(recorder.requests) == 1


async def test_associations_are_followed_across_pages() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/crm/v4/"):
            if request.url.params.get("after") == "page-2":
                return httpx.Response(200, json={"results": [{"toObjectId": 12}]})
            return httpx.Response(
                200,
                json={
                    "results": [{"toObjectId": 11}],
                    "paging": {"next": {"after": "page-2"}},
                },
            )
        return httpx.Response(200, json={"results": []})

    sink, recorder = _sink(respond)
    await sink.sota_cards("501")

    assert _body(recorder.requests[-1])["inputs"] == [{"id": "11"}, {"id": "12"}]


async def test_create_card_adds_the_pipeline_and_links_the_contact() -> None:
    sink, recorder = _sink(lambda _: httpx.Response(201, json={"id": "900"}))
    card_id = await sink.create_card(
        "501", {"dealname": "Ana", PROP_STAGE: "s1", PROP_SOTA: "true"}
    )

    assert card_id == "900"
    [request] = recorder.requests
    assert (request.method, request.url.path) == ("POST", "/crm/v3/objects/deals")
    body = _body(request)
    assert body["properties"] == {
        "dealname": "Ana",
        PROP_STAGE: "s1",
        PROP_SOTA: "true",
        "pipeline": PIPELINE,
    }
    assert body["associations"] == [
        {
            "to": {"id": "501"},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 3}],
        }
    ]


async def test_update_card_patches_only_what_changed_and_skips_an_empty_change() -> None:
    sink, recorder = _sink(lambda _: httpx.Response(200, json={"id": "11"}))
    await sink.update_card("11", {})
    assert recorder.requests == []

    await sink.update_card("11", {PROP_COUNT: "2"})
    [request] = recorder.requests
    assert (request.method, request.url.path) == ("PATCH", "/crm/v3/objects/deals/11")
    assert _body(request) == {"properties": {PROP_COUNT: "2"}}


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, CrmRateLimited),
        (401, CrmAuthFailed),
        (403, CrmAuthFailed),
        (500, CrmError),
        (400, CrmError),
    ],
)
async def test_hubspot_errors_map_to_the_sync_errors(status: int, error: type[CrmError]) -> None:
    sink, _ = _sink(lambda _: httpx.Response(status, json={"message": "contains ana@uni.edu"}))
    with pytest.raises(error) as raised:
        await sink.update_card("11", {PROP_COUNT: "2"})
    # INVARIANT: the error names the status only; a response body can echo request data.
    assert raised.value.status == status
    assert str(raised.value) == f"hubspot_{status}"


async def test_a_network_failure_is_a_retryable_error() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    sink, _ = _sink(respond)
    with pytest.raises(CrmError) as raised:
        await sink.find_contact("ana@uni.edu")
    assert type(raised.value) is CrmError
    assert (raised.value.status, str(raised.value)) == (None, "hubspot_unreachable")


def _one_card(properties: dict[str, str | None], history: dict[str, list[dict[str, str]]]):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/crm/v4/"):
            return httpx.Response(200, json={"results": [{"toObjectId": 11}]})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "11",
                        "properties": {"pipeline": PIPELINE, PROP_STAGE: "s1", **properties},
                        "propertiesWithHistory": history,
                    }
                ]
            },
        )

    return respond


def _entry(source_type: str, source_id: str, timestamp: str) -> dict[str, str]:
    return {"value": "x", "sourceType": source_type, "sourceId": source_id, "timestamp": timestamp}


@pytest.mark.parametrize(
    ("entries", "protected"),
    [
        ([_entry("INTEGRATION", APP_ID, "2026-11-20T10:00:00Z")], False),
        # Another private app or integration: not ours, so kept.
        ([_entry("INTEGRATION", "99999", "2026-11-20T10:00:00Z")], True),
        # A workflow, an import, a person: kept.
        ([_entry("AUTOMATION_PLATFORM", "wf-1", "2026-11-20T10:00:00Z")], True),
        ([_entry("IMPORT", "imp-1", "2026-11-20T10:00:00Z")], True),
        ([_entry("CRM_UI", "user-7", "2026-11-20T10:00:00Z")], True),
        # The newest entry decides, whatever the array order.
        (
            [
                _entry("INTEGRATION", APP_ID, "2026-11-19T10:00:00Z"),
                _entry("CRM_UI", "user-7", "2026-11-20T10:00:00Z"),
            ],
            True,
        ),
        (
            [
                _entry("CRM_UI", "user-7", "2026-11-19T10:00:00Z"),
                _entry("INTEGRATION", APP_ID, "2026-11-20T10:00:00Z"),
            ],
            False,
        ),
        # A filled value with no history is not provably ours.
        ([], True),
    ],
)
async def test_only_this_apps_own_newest_write_may_be_replaced(
    entries: list[dict[str, str]], protected: bool
) -> None:
    sink, _ = _sink(_one_card({PROP_ENTRY: "x"}, {PROP_ENTRY: entries}))
    [card] = await sink.sota_cards("501")
    assert (PROP_ENTRY in card.protected) is protected


async def test_without_an_app_id_every_filled_value_is_kept() -> None:
    history = {PROP_ENTRY: [_entry("INTEGRATION", APP_ID, "2026-11-20T10:00:00Z")]}
    sink, _ = _sink(_one_card({PROP_ENTRY: "x", PROP_COUNT: None}, history), app_id=None)
    [card] = await sink.sota_cards("501")
    assert card.protected == frozenset({PROP_ENTRY})


async def test_an_empty_value_is_never_protected() -> None:
    history = {PROP_ENTRY: [_entry("CRM_UI", "user-7", "2026-11-20T10:00:00Z")]}
    sink, _ = _sink(_one_card({PROP_ENTRY: ""}, history))
    [card] = await sink.sota_cards("501")
    assert card.protected == frozenset()


async def test_a_read_timeout_is_a_retryable_error_with_no_status() -> None:
    # WHY: a create whose response is lost surfaces as this error; the next run re-reads the
    # person's cards before creating anything (tests/unit/test_hubspot_sync_job.py).
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no response", request=request)

    sink, _ = _sink(respond)
    with pytest.raises(CrmError) as raised:
        await sink.create_card("501", {"dealname": "Ana"})
    assert type(raised.value) is CrmError and raised.value.status is None
