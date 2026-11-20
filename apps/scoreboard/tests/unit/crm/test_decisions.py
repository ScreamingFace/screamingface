"""The HubSpot sync's rules, with no database and no network (OME-1504).

FEATURE: every outside leaderboard submission moves the submitter's card on the 😱 SOTA pipeline.

STORY: as someone on the program team, I see each outside submitter's card at Submission 1, 2 or 3
by how many distinct recipes they have submitted, with a link to their newest result, the date
they were last active, and a SOTA flag once a fusion of theirs beats every solo model on a board,
without the sync ever undoing something I set by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from scoreboard.crm.decisions import (
    PROP_COUNT,
    PROP_ENTRY,
    PROP_SOTA,
    PROP_SOTA_ENTRY,
    PROP_STAGE,
    CardState,
    Stages,
    Submission,
    card_changes,
    card_name,
    ineligible_reason,
    last_active_to_write,
    new_card_properties,
    target_for,
)

BASE = "https://leaderboard.example"
STAGES = Stages(
    early=("onboarding", "engaged"),
    submissions=("sub-1", "sub-2", "sub-3"),
    dropped_out="dropped",
)


def _submission(
    benchmark: str,
    spec: str,
    day: int,
    *,
    sota: bool = False,
) -> Submission:
    return Submission(
        benchmark_id=benchmark,
        spec_id=spec,
        submitted_at=datetime(2026, 11, day, 12, 0, tzinfo=UTC),
        sota_qualified=sota,
    )


def _card(stage: str, values: dict[str, str | None] | None = None, hand: set[str] | None = None):
    return CardState(
        id="deal-1",
        stage_id=stage,
        values=values or {},
        hand_set=frozenset(hand or set()),
    )


# --- who is sent at all ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("submitted_by", "reason"),
    [
        (None, "no_submitter"),
        ("", "no_submitter"),
        ("filip.boltuzic", "not_an_email"),
        ("@uni.edu", "not_an_email"),
        ("ana@", "not_an_email"),
        ("khoa@openmined.org", "internal"),
        ("Khoa@OpenMined.ORG", "internal"),
        ("friend@partner.org", "internal"),
        ("FRIEND@partner.org", "internal"),
        ("ana@uni.edu", None),
    ],
)
def test_who_is_ineligible_and_why(submitted_by: str | None, reason: str | None) -> None:
    # INVARIANT: the team and anything that is not a verified email never become HubSpot contacts.
    assert ineligible_reason(submitted_by, internal_emails=frozenset({"friend@partner.org"})) == (
        reason
    )


# --- what the card should show ---------------------------------------------------------------


def test_reruns_of_one_recipe_on_one_board_count_once() -> None:
    target = target_for(
        [_submission("mmlu", "r1", 1), _submission("mmlu", "r1", 2), _submission("mmlu", "r1", 3)],
        STAGES,
        BASE,
    )
    assert (target.submission_count, target.stage_id) == (1, "sub-1")


def test_one_recipe_on_two_boards_counts_twice() -> None:
    target = target_for(
        [_submission("mmlu", "r1", 1), _submission("gpqa", "r1", 2)],
        STAGES,
        BASE,
    )
    assert (target.submission_count, target.stage_id) == (2, "sub-2")


@pytest.mark.parametrize(
    ("pairs", "stage"), [(1, "sub-1"), (2, "sub-2"), (3, "sub-3"), (7, "sub-3")]
)
def test_stage_follows_the_count_and_stops_at_submission_3(pairs: int, stage: str) -> None:
    submissions = [_submission(f"board-{i}", "r", 1 + i) for i in range(pairs)]
    assert target_for(submissions, STAGES, BASE).stage_id == stage


def test_entry_link_and_last_active_come_from_the_newest_submission() -> None:
    target = target_for(
        [_submission("mmlu", "old one", 1), _submission("gpqa", "new one", 9)],
        STAGES,
        BASE,
    )
    assert target.entry_url == f"{BASE}/spec.html?benchmark=gpqa&spec=new%20one"
    assert target.last_active == date(2026, 11, 9)


def test_the_sota_entry_is_the_first_qualifying_submission() -> None:
    target = target_for(
        [
            _submission("mmlu", "solo", 1),
            _submission("gpqa", "late fusion", 9, sota=True),
            _submission("hle", "early fusion", 4, sota=True),
        ],
        STAGES,
        BASE,
    )
    assert target.sota_entry_url == f"{BASE}/spec.html?benchmark=hle&spec=early%20fusion"


def test_no_qualifying_submission_means_no_sota_entry() -> None:
    assert target_for([_submission("mmlu", "solo", 1)], STAGES, BASE).sota_entry_url is None


def test_a_person_with_no_submissions_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        target_for([], STAGES, BASE)


# --- what changes on an existing card --------------------------------------------------------


def _target(pairs: int = 2, *, sota: bool = False):
    submissions = [_submission(f"board-{i}", "r", 1 + i, sota=sota) for i in range(pairs)]
    return target_for(submissions, STAGES, BASE)


@pytest.mark.parametrize("current", ["onboarding", "engaged", "sub-1"])
def test_a_card_before_the_target_moves_forward(current: str) -> None:
    changes = card_changes(_card(current), _target(2), STAGES)
    assert changes is not None and changes[PROP_STAGE] == "sub-2"


@pytest.mark.parametrize("current", ["sub-2", "sub-3"])
def test_a_card_never_moves_backwards(current: str) -> None:
    changes = card_changes(_card(current), _target(2), STAGES)
    assert changes is not None and PROP_STAGE not in changes


@pytest.mark.parametrize("current", ["project-completed", "publication", "some-new-stage"])
def test_a_card_in_a_hand_managed_stage_keeps_it_but_gets_its_fields(current: str) -> None:
    # WHY: Project completed and Publication are set by hand and sit after Submission 3; an
    # unknown stage is treated the same way, so a stage added later is never overwritten.
    changes = card_changes(_card(current), _target(2), STAGES)
    assert changes is not None
    assert PROP_STAGE not in changes
    assert changes[PROP_COUNT] == "2"


def test_a_dropped_out_card_is_left_entirely_alone() -> None:
    # INVARIANT (Filip, 2026-11-19): not even its fields change when the person submits again.
    assert card_changes(_card("dropped"), _target(3, sota=True), STAGES) is None


def test_the_count_and_entry_link_are_written_when_they_differ() -> None:
    target = _target(2)
    changes = card_changes(_card("sub-2", {PROP_COUNT: "1", PROP_ENTRY: "old"}), target, STAGES)
    assert changes == {PROP_COUNT: "2", PROP_ENTRY: target.entry_url}


def test_nothing_is_written_when_the_card_already_matches() -> None:
    target = _target(2)
    card = _card("sub-2", {PROP_COUNT: "2", PROP_ENTRY: target.entry_url})
    assert card_changes(card, target, STAGES) == {}


def test_a_value_a_person_typed_is_never_overwritten() -> None:
    # INVARIANT (Bennett's rule): a property whose latest value came from a person stays.
    card = _card("sub-1", {PROP_COUNT: "5", PROP_ENTRY: "typed"}, hand={PROP_COUNT, PROP_ENTRY})
    assert card_changes(card, _target(2), STAGES) == {PROP_STAGE: "sub-2"}


def test_the_sota_flag_is_set_with_its_entry() -> None:
    target = _target(1, sota=True)
    changes = card_changes(
        _card("sub-1", {PROP_COUNT: "1", PROP_ENTRY: target.entry_url}), target, STAGES
    )
    assert changes == {PROP_SOTA: "true", PROP_SOTA_ENTRY: target.sota_entry_url}


def test_the_sota_flag_once_set_is_never_moved_to_a_later_entry() -> None:
    target = _target(1, sota=True)
    card = _card(
        "sub-1",
        {
            PROP_COUNT: "1",
            PROP_ENTRY: target.entry_url,
            PROP_SOTA: "true",
            PROP_SOTA_ENTRY: "first",
        },
    )
    assert card_changes(card, target, STAGES) == {}


def test_a_sota_flag_a_person_set_is_left_alone() -> None:
    target = _target(1, sota=True)
    card = _card(
        "sub-1",
        {PROP_COUNT: "1", PROP_ENTRY: target.entry_url, PROP_SOTA: "false"},
        hand={PROP_SOTA},
    )
    assert card_changes(card, target, STAGES) == {}


# --- a new card ------------------------------------------------------------------------------


def test_a_new_card_carries_the_stage_fields_and_name() -> None:
    target = _target(3, sota=True)
    assert new_card_properties(target, name="Ana Silva") == {
        "dealname": "Ana Silva",
        PROP_STAGE: "sub-3",
        PROP_COUNT: "3",
        PROP_ENTRY: target.entry_url,
        PROP_SOTA: "true",
        PROP_SOTA_ENTRY: target.sota_entry_url,
    }


def test_a_new_card_without_sota_does_not_mention_it() -> None:
    properties = new_card_properties(_target(1), name="Ana Silva")
    assert PROP_SOTA not in properties and PROP_SOTA_ENTRY not in properties


@pytest.mark.parametrize(
    ("first", "last", "name"),
    [
        ("Ana", "Silva", "Ana Silva"),
        ("Ana", None, "Ana"),
        (None, "Silva", "Silva"),
        ("  Ana ", " Silva ", "Ana Silva"),
        (None, None, "ana@uni.edu"),
        ("", "", "ana@uni.edu"),
        ("Unknown", None, "ana@uni.edu"),
    ],
)
def test_a_card_is_named_after_the_person_or_their_email(
    first: str | None, last: str | None, name: str
) -> None:
    # WHY: 32 of the 35 existing SOTA cards are "<first> <last>"; a card called "Unknown" would be
    # useless on the board, so a contact without a real name gives its email.
    assert card_name(first, last, "ana@uni.edu") == name


# --- the contact's last active date ----------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "newest", "write"),
    [
        (None, date(2026, 11, 9), date(2026, 11, 9)),
        (date(2026, 11, 1), date(2026, 11, 9), date(2026, 11, 9)),
        (date(2026, 11, 9), date(2026, 11, 9), None),
        (date(2026, 11, 12), date(2026, 11, 9), None),
    ],
)
def test_last_active_only_moves_forward(
    stored: date | None, newest: date, write: date | None
) -> None:
    assert last_active_to_write(stored, newest) == write
