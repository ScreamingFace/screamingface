"""The HubSpot sync job: what it queues, what it sends, and how it survives HubSpot (OME-1504).

FEATURE: every outside submission reaches the submitter's card on the 😱 SOTA pipeline within one
CronJob period, through a queue table, so a HubSpot outage never touches the submit path.

STORY: as someone on the program team, I see a new outside submitter appear in HubSpot with a card
at the right stage, while the team's own runs, reruns and private boards never show up.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from tortoise.transactions import in_transaction
from url4 import expr, render, src, text

from scoreboard.crm.decisions import (
    PROP_COUNT,
    PROP_ENTRY,
    PROP_SOTA,
    PROP_SOTA_ENTRY,
    PROP_STAGE,
    CardState,
    Stages,
)
from scoreboard.crm.port import Contact, CrmAuthFailed, CrmError, CrmRateLimited
from scoreboard.db import DEFAULT_CONNECTION
from scoreboard.delete_scores import _delete_rows
from scoreboard.hubspot_sync import SyncConfig, backoff, run_sync
from scoreboard.scores.models import Baseline, Benchmark, HubSpotSyncRecord, Score

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CONFIG = SyncConfig(
    stages=Stages(
        early=("onboarding", "engaged"), submissions=("s1", "s2", "s3"), dropped_out="out"
    ),
    base_url="https://board.example",
    internal_emails=frozenset({"friend@partner.org"}),
)


class FakeSink:
    """An in-memory HubSpot: contacts by email, cards by contact id, every write recorded."""

    def __init__(self) -> None:
        self.contacts: dict[str, Contact] = {}
        self.cards: dict[str, list[CardState]] = {}
        self.writes: list[tuple[str, str, Any]] = []
        self.fail_for: dict[str, CrmError] = {}
        self.lose_create_response: CrmError | None = None

    def _maybe_fail(self, email: str) -> None:
        if email in self.fail_for:
            raise self.fail_for[email]

    async def find_contact(self, email: str) -> Contact | None:
        self._maybe_fail(email)
        return self.contacts.get(email)

    async def create_contact(self, email: str) -> Contact:
        contact = Contact(
            id=f"c-{len(self.contacts) + 1}", first_name="Unknown", last_name=None, last_active=None
        )
        self.contacts[email] = contact
        self.writes.append(("create_contact", contact.id, email))
        return contact

    async def set_last_active(self, contact_id: str, day: date) -> None:
        self.writes.append(("set_last_active", contact_id, day))
        for email, contact in self.contacts.items():
            if contact.id == contact_id:
                self.contacts[email] = replace(contact, last_active=day)

    async def sota_cards(self, contact_id: str) -> list[CardState]:
        return list(self.cards.get(contact_id, []))

    async def create_card(self, contact_id: str, properties: Mapping[str, str]) -> str:
        self.writes.append(("create_card", contact_id, dict(properties)))
        if self.lose_create_response is not None:
            # HubSpot committed the card (and its association), but the response never arrived.
            self.cards[contact_id] = [
                CardState("new-card", properties["dealstage"], dict(properties), frozenset())
            ]
            error, self.lose_create_response = self.lose_create_response, None
            raise error
        return "new-card"

    async def update_card(self, card_id: str, properties: Mapping[str, str]) -> None:
        self.writes.append(("update_card", card_id, dict(properties)))


# WHY the Recipe kind, not the Client's `candidate_kind` label: rule B reads the Recipe the run
# carries; one model is solo, anything else a fusion (Filip and Irina, 2026-11-26).
SOLO = "model"
DUO = "fusion"


def _stored(recipe_kind: str) -> str:
    """A stored url4 expression whose Candidate carries a Recipe of `recipe_kind`."""
    recipe = json.dumps({"schema": "screamingface.recipe.v1", "recipe": {"kind": recipe_kind}})
    candidate = render(
        expr(
            src("/openrouter/acme/m1", name="model_1"),
            src(text(recipe), name="_sf_recipe", weight=0.0),
            intent=text("$model_1"),
        )
    )
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/mmlu/aggregate", name="result"),
            intent=text(""),
        )
    )


async def _board(benchmark_id: str = "mmlu", *, visibility: str = "public") -> None:
    await Benchmark.create(id=benchmark_id, display_name=benchmark_id, visibility=visibility)


async def _score(
    submitted_by: str | None,
    *,
    benchmark: str = "mmlu",
    spec: str = "recipe-a",
    score: float = 0.5,
    day: int = 10,
    recipe: str | None = None,
) -> Score:
    row = await Score.create(
        spec_id=spec,
        url4_expression="url4://x" if recipe is None else _stored(recipe),
        score=score,
        total_questions=10,
        ran_with_providers=[],
        benchmark_id=benchmark,
        submitted_by=submitted_by,
    )
    await Score.filter(id=row.id).update(submitted_at=datetime(2026, 11, day, 9, 0, tzinfo=UTC))
    return row


async def _rows() -> dict[uuid.UUID, SimpleNamespace]:
    rows = await HubSpotSyncRecord.all().values()
    return {uuid.UUID(str(row["score_id"])): SimpleNamespace(**row) for row in rows}


# --- queueing --------------------------------------------------------------------------------


async def test_internal_non_email_and_private_board_scores_are_skipped_with_a_reason(
    tortoise_db: None,
) -> None:
    await _board()
    await _board("secret", visibility="private")
    internal = await _score("khoa@openmined.org")
    partner = await _score("friend@partner.org", spec="b")
    not_email = await _score("filip.boltuzic", spec="c")
    private = await _score("ana@uni.edu", benchmark="secret")
    sink = FakeSink()

    await run_sync(sink, CONFIG, now=NOW)

    rows = await _rows()
    assert {key: (row.status, row.reason) for key, row in rows.items()} == {
        internal.id: ("skipped", "internal"),
        partner.id: ("skipped", "internal"),
        not_email.id: ("skipped", "not_an_email"),
        private.id: ("skipped", "private_board"),
    }
    assert sink.writes == []


async def test_a_new_outside_submitter_gets_a_contact_and_a_card(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu", spec="my recipe", day=9)
    sink = FakeSink()

    summary = await run_sync(sink, CONFIG, now=NOW)

    assert sink.writes == [
        ("create_contact", "c-1", "ana@uni.edu"),
        ("set_last_active", "c-1", date(2026, 11, 9)),
        (
            "create_card",
            "c-1",
            {
                "dealname": "ana@uni.edu",
                PROP_STAGE: "s1",
                PROP_COUNT: "1",
                PROP_ENTRY: "https://board.example/spec.html?benchmark=mmlu&spec=my%20recipe",
            },
        ),
    ]
    sync_row = (await _rows())[row.id]
    assert (sync_row.status, sync_row.attempts) == ("sent", 0)
    assert (summary.sent, summary.failed) == (1, 0)


async def test_an_existing_card_moves_forward_by_distinct_recipes(tortoise_db: None) -> None:
    await _board()
    await _board("gpqa")
    await _score("ana@uni.edu", spec="r1", day=1)
    await _score("ana@uni.edu", spec="r1", day=2)  # a rerun: no new submission
    await _score("ana@uni.edu", spec="r2", day=3)
    await _score("ana@uni.edu", benchmark="gpqa", spec="r1", day=4)
    sink = FakeSink()
    sink.contacts["ana@uni.edu"] = Contact("c-9", "Ana", "Silva", date(2026, 11, 30))
    sink.cards["c-9"] = [CardState("deal-9", "s1", {PROP_COUNT: "1"}, frozenset())]

    await run_sync(sink, CONFIG, now=NOW)

    [update] = sink.writes
    assert update[0:2] == ("update_card", "deal-9")
    assert update[2][PROP_STAGE] == "s3"
    assert update[2][PROP_COUNT] == "3"


async def test_a_rerun_after_sending_writes_nothing_new(tortoise_db: None) -> None:
    await _board()
    await _score("ana@uni.edu", spec="r1", day=1)
    sink = FakeSink()
    await run_sync(sink, CONFIG, now=NOW)
    first_url = sink.writes[-1][2][PROP_ENTRY]
    sink.cards["c-1"] = [
        CardState("deal-1", "s1", {PROP_COUNT: "1", PROP_ENTRY: first_url}, frozenset())
    ]
    sink.writes.clear()
    await _score("ana@uni.edu", spec="r1", day=1)

    await run_sync(sink, CONFIG, now=NOW)

    assert sink.writes == [("update_card", "deal-1", {})]


async def test_a_dropped_out_card_is_left_alone_and_its_rows_are_done(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.contacts["ana@uni.edu"] = Contact("c-9", "Ana", None, None)
    sink.cards["c-9"] = [CardState("deal-9", "out", {}, frozenset())]

    await run_sync(sink, CONFIG, now=NOW)

    assert sink.writes == []
    sync_row = (await _rows())[row.id]
    # WHY sent, not skipped: if the team brings the card back, these rows must still count.
    assert (sync_row.status, sync_row.reason) == ("sent", "dropped_out")


async def test_two_sota_cards_change_nothing_and_wait_for_a_person(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.contacts["ana@uni.edu"] = Contact("c-9", "Ana", None, None)
    sink.cards["c-9"] = [
        CardState("deal-1", "s1", {}, frozenset()),
        CardState("deal-2", "s2", {}, frozenset()),
    ]

    await run_sync(sink, CONFIG, now=NOW)

    assert sink.writes == []
    sync_row = (await _rows())[row.id]
    assert (sync_row.status, sync_row.reason, sync_row.attempts) == ("failed", "ambiguous_card", 1)


# --- HubSpot failures ------------------------------------------------------------------------


async def test_a_hubspot_error_is_retried_after_backoff(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.fail_for["ana@uni.edu"] = CrmError(503)

    await run_sync(sink, CONFIG, now=NOW)
    failed = (await _rows())[row.id]
    assert (failed.status, failed.reason, failed.attempts) == ("failed", "hubspot_503", 1)
    assert failed.next_attempt_at == NOW + timedelta(minutes=5)

    del sink.fail_for["ana@uni.edu"]
    await run_sync(sink, CONFIG, now=NOW + timedelta(minutes=1))
    assert sink.writes == []  # not due yet

    await run_sync(sink, CONFIG, now=NOW + timedelta(minutes=6))
    assert (await _rows())[row.id].status == "sent"


@pytest.mark.parametrize(
    ("attempts", "wait"),
    [
        (1, timedelta(minutes=5)),
        (2, timedelta(minutes=10)),
        (4, timedelta(minutes=40)),
        (12, timedelta(hours=6)),
    ],
)
async def test_backoff_doubles_and_is_capped_at_six_hours(attempts: int, wait: timedelta) -> None:
    assert backoff(attempts) == wait


async def test_rate_limiting_stops_the_run_without_spending_attempts(tortoise_db: None) -> None:
    await _board()
    first = await _score("a@uni.edu", spec="r1")
    second = await _score("b@uni.edu", spec="r2")
    sink = FakeSink()
    sink.fail_for["a@uni.edu"] = CrmRateLimited(429)
    sink.fail_for["b@uni.edu"] = CrmRateLimited(429)

    summary = await run_sync(sink, CONFIG, now=NOW)

    rows = await _rows()
    assert {(rows[i].status, rows[i].attempts) for i in (first.id, second.id)} == {("pending", 0)}
    assert summary.rate_limited is True


async def test_an_auth_failure_stops_the_run_loudly(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.fail_for["ana@uni.edu"] = CrmAuthFailed(401)

    with pytest.raises(CrmAuthFailed):
        await run_sync(sink, CONFIG, now=NOW)

    sync_row = (await _rows())[row.id]
    assert (sync_row.status, sync_row.attempts) == ("pending", 0)


# --- no token and dry run --------------------------------------------------------------------


async def test_without_a_sink_nothing_is_queued_or_sent(tortoise_db: None) -> None:
    await _board()
    await _score("ana@uni.edu")

    summary = await run_sync(None, CONFIG, now=NOW)

    assert await HubSpotSyncRecord.all().count() == 0
    assert summary.waiting == 1


async def test_a_dry_run_reads_but_changes_no_row(tortoise_db: None) -> None:
    await _board()
    await _score("ana@uni.edu")
    sink = FakeSink()

    summary = await run_sync(sink, CONFIG, now=NOW, dry_run=True)

    assert sink.writes == []
    assert await HubSpotSyncRecord.all().count() == 0
    assert summary.sent == 1


# --- the SOTA flag (rule B) ------------------------------------------------------------------


async def test_a_fusion_beating_every_solo_model_sets_the_sota_flag(tortoise_db: None) -> None:
    await _board()
    await _score("rival@lab.org", spec="solo", score=0.70, recipe=SOLO)
    await _score("ana@uni.edu", spec="fusion", score=0.80, recipe=DUO)
    sink = FakeSink()

    await run_sync(sink, CONFIG, now=NOW)

    created = [
        write[2]
        for write in sink.writes
        if write[0] == "create_card" and write[2]["dealname"] == "ana@uni.edu"
    ]
    [properties] = created
    assert properties[PROP_SOTA] == "true"
    assert (
        properties[PROP_SOTA_ENTRY] == "https://board.example/spec.html?benchmark=mmlu&spec=fusion"
    )


@pytest.mark.parametrize(
    ("fusion_score", "other_recipe", "baseline_score", "qualifies"),
    [
        (0.80, SOLO, None, True),
        (0.70, SOLO, None, False),  # a tie is not a win
        (0.60, SOLO, None, False),
        (0.80, None, None, False),  # no solo reference on the board
        (0.80, DUO, None, False),  # only other fusions: nothing solo to beat
        (0.80, None, 0.75, True),  # an imported baseline is a solo reference
        (0.80, SOLO, 0.85, False),
    ],
)
async def test_rule_b(
    tortoise_db: None,
    fusion_score: float,
    other_recipe: str | None,
    baseline_score: float | None,
    qualifies: bool,
) -> None:
    await _board()
    if other_recipe is not None:
        await _score("rival@lab.org", spec="other", score=0.70, recipe=other_recipe)
    if baseline_score is not None:
        await Baseline.create(
            benchmark_id="mmlu", model_name="gpt-x", score=baseline_score, source="lmarena"
        )
    fusion = await _score("ana@uni.edu", spec="fusion", score=fusion_score, recipe=DUO)

    await run_sync(FakeSink(), CONFIG, now=NOW)

    assert (await _rows())[fusion.id].sota_qualified is qualifies


async def test_a_solo_model_never_qualifies_even_alone_at_the_top(tortoise_db: None) -> None:
    await _board()
    await _score("rival@lab.org", spec="weak", score=0.2, recipe=SOLO)
    solo = await _score("ana@uni.edu", spec="solo", score=0.9, recipe=SOLO)

    await run_sync(FakeSink(), CONFIG, now=NOW)

    assert (await _rows())[solo.id].sota_qualified is False


async def test_a_pipeline_recipe_is_a_fusion(tortoise_db: None) -> None:
    # Shuai Wu's gdpval-text duo: two models and a synthesizer, a `pipeline` Recipe.
    await _board()
    await _score("rival@lab.org", spec="solo", score=0.79, recipe=SOLO)
    duo = await _score("ana@uni.edu", spec="duo", score=0.81, recipe="pipeline")

    await run_sync(FakeSink(), CONFIG, now=NOW)

    assert (await _rows())[duo.id].sota_qualified is True


async def test_one_model_sampled_and_combined_is_a_fusion(tortoise_db: None) -> None:
    # Akshat Gupta's argon x3 with a selector: one model, a `fusion` Recipe ("self fusion").
    await _board()
    await _score("rival@lab.org", spec="solo", score=0.69, recipe=SOLO)
    sampled = await _score("ana@uni.edu", spec="argon-x3", score=0.70, recipe=DUO)

    await run_sync(FakeSink(), CONFIG, now=NOW)

    assert (await _rows())[sampled.id].sota_qualified is True


async def test_a_run_without_a_readable_recipe_is_neither_fusion_nor_solo(
    tortoise_db: None,
) -> None:
    await _board()
    await _score("rival@lab.org", spec="old", score=0.95)
    await _score("cy@uni.edu", spec="solo", score=0.70, recipe=SOLO)
    fusion = await _score("ana@uni.edu", spec="fusion", score=0.80, recipe=DUO)
    old_fusion = await _score("bo@uni.edu", spec="old-fusion", score=0.99)

    await run_sync(FakeSink(), CONFIG, now=NOW)

    rows = await _rows()
    assert (rows[fusion.id].sota_qualified, rows[old_fusion.id].sota_qualified) == (True, False)


# --- deleting scores still works with sync rows ----------------------------------------------


async def test_deleting_scores_removes_their_sync_rows_and_counts_scores_only(
    tortoise_db: None,
) -> None:
    await _board()
    first = await _score("ana@uni.edu", spec="r1")
    second = await _score("ana@uni.edu", spec="r2")
    await run_sync(FakeSink(), CONFIG, now=NOW)

    async with in_transaction(DEFAULT_CONNECTION) as connection:
        deleted = await _delete_rows(connection, [first.id, second.id])

    assert deleted == 2
    assert await HubSpotSyncRecord.all().count() == 0


# --- review of #1981: visibility, re-grades, a lost create response ---------------------------


async def test_a_pending_row_whose_board_goes_private_is_never_sent(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.fail_for["ana@uni.edu"] = CrmRateLimited(429)
    await run_sync(sink, CONFIG, now=NOW)
    assert (await _rows())[row.id].status == "pending"
    await Benchmark.filter(id="mmlu").update(visibility="private")
    del sink.fail_for["ana@uni.edu"]

    await run_sync(sink, CONFIG, now=NOW + timedelta(minutes=1))

    assert sink.writes == []
    sync_row = (await _rows())[row.id]
    assert (sync_row.status, sync_row.reason) == ("skipped", "private_board")


async def test_a_failed_row_whose_board_goes_private_is_never_retried(tortoise_db: None) -> None:
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.fail_for["ana@uni.edu"] = CrmError(503)
    await run_sync(sink, CONFIG, now=NOW)
    assert (await _rows())[row.id].status == "failed"
    await Benchmark.filter(id="mmlu").update(visibility="private")
    del sink.fail_for["ana@uni.edu"]

    await run_sync(sink, CONFIG, now=NOW + timedelta(hours=1))

    assert sink.writes == []
    sync_row = (await _rows())[row.id]
    assert (sync_row.status, sync_row.reason) == ("skipped", "private_board")


async def test_a_board_gone_private_drops_out_of_the_count(tortoise_db: None) -> None:
    await _board()
    await _board("gpqa")
    await _score("ana@uni.edu", spec="r1", day=1)
    sink = FakeSink()
    await run_sync(sink, CONFIG, now=NOW)
    await Benchmark.filter(id="mmlu").update(visibility="private")
    sink.cards["c-1"] = [CardState("deal-1", "s1", {}, frozenset())]
    sink.writes.clear()
    await _score("ana@uni.edu", benchmark="gpqa", spec="r2", day=2)

    await run_sync(sink, CONFIG, now=NOW)

    [update] = [write for write in sink.writes if write[0] == "update_card"]
    # Only the gpqa result counts now, and the link never points at the hidden board.
    assert update[2][PROP_COUNT] == "1"
    assert update[2][PROP_ENTRY] == "https://board.example/spec.html?benchmark=gpqa&spec=r2"


async def test_a_regrade_is_skipped_and_never_counted(tortoise_db: None) -> None:
    await _board()
    original = await _score("ana@uni.edu", spec="r1", day=1)
    regrade = await Score.create(
        spec_id="r1",
        url4_expression="url4://x",
        score=0.9,
        total_questions=10,
        ran_with_providers=[],
        benchmark_id="mmlu",
        submitted_by="ana@uni.edu",
        regraded_from_id=original.id,
        benchmark_revision="rev-2",
    )
    sink = FakeSink()

    await run_sync(sink, CONFIG, now=NOW)

    rows = await _rows()
    assert (rows[regrade.id].status, rows[regrade.id].reason) == ("skipped", "regrade")
    [(_, _, properties)] = [write for write in sink.writes if write[0] == "create_card"]
    assert properties[PROP_COUNT] == "1"
    # The activity date is the original run's, not the re-grade's.
    assert ("set_last_active", "c-1", date(2026, 11, 1)) in sink.writes


async def test_a_lost_create_response_never_makes_a_second_card(tortoise_db: None) -> None:
    # WHY no extra HubSpot property: every attempt re-reads the person's SOTA cards before it
    # creates one, and a card is created together with its association to the contact, so a
    # card HubSpot committed is found on the retry and updated instead.
    await _board()
    row = await _score("ana@uni.edu")
    sink = FakeSink()
    sink.lose_create_response = CrmError(None)

    await run_sync(sink, CONFIG, now=NOW)
    failed = (await _rows())[row.id]
    assert (failed.status, failed.reason) == ("failed", "hubspot_unreachable")

    await run_sync(sink, CONFIG, now=NOW + timedelta(minutes=6))

    assert [write[0] for write in sink.writes].count("create_card") == 1
    assert sink.writes[-1][0:2] == ("update_card", "new-card")
    assert (await _rows())[row.id].status == "sent"
