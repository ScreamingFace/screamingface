"""What the HubSpot sync writes, decided without a database or a network.

FEATURE: OME-1504 — every outside leaderboard submission moves the submitter's card on the
😱 SOTA pipeline (spec: docs/spec/2026-11-18-hubspot-submission-sync.md).

WHY pure: these rules are what the program team relies on (who becomes a contact, which stage, when
the SOTA flag is set, what is never overwritten). Keeping them free of I/O makes every rule a
one-line test and keeps the adapter and the job free of judgement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

# The HubSpot internal names this sync writes, on the deal (card) and on the contact.
# AIDEV-NOTE: Bennett named the SOTA fields on 2026-11-19 with the `sf_` prefix the other 😱 fields
# use; read the pipeline schema again before renaming any of them.
PROP_STAGE = "dealstage"
PROP_COUNT = "sf_submission_count"
PROP_ENTRY = "sf_leaderboard_url"
PROP_SOTA = "sf_sota_achieved"
PROP_SOTA_ENTRY = "sf_sota_entry"
PROP_LAST_ACTIVE = "sf_last_active_date"

# INVARIANT: the whole team works under this domain; none of it is ever sent.
INTERNAL_DOMAIN = "openmined.org"
# WHY: a contact the sync creates has no name yet (decision 2026-11-18); the identity provider
# Stephen's team is planning will replace it.
UNKNOWN_NAME = "Unknown"


@dataclass(frozen=True)
class Stages:
    """The 😱 SOTA pipeline's stage ids the sync knows about, by HubSpot id.

    INVARIANT: matched by id, never by label. `early` and `submissions` are in pipeline order and
    are the only stages a card is moved FROM; every other stage (Project completed, Publication,
    anything added later) is hand-managed and kept.
    """

    early: tuple[str, ...]
    submissions: tuple[str, str, str]
    dropped_out: str

    @property
    def movable(self) -> tuple[str, ...]:
        return (*self.early, *self.submissions)


@dataclass(frozen=True)
class Submission:
    """One eligible score of one submitter."""

    benchmark_id: str
    spec_id: str
    submitted_at: datetime
    # Rule B, decided when the score was queued and never recomputed.
    sota_qualified: bool


@dataclass(frozen=True)
class Target:
    """What one submitter's card should show, from all their eligible scores."""

    submission_count: int
    stage_id: str
    entry_url: str
    last_active: date
    sota_entry_url: str | None


@dataclass(frozen=True)
class CardState:
    """An existing SOTA card as HubSpot holds it."""

    id: str
    stage_id: str
    values: Mapping[str, str | None]
    # Properties whose latest value came from a person (Bennett's rule: never overwrite those).
    hand_set: frozenset[str]


def ineligible_reason(submitted_by: str | None, *, internal_emails: frozenset[str]) -> str | None:
    """Why a submitter is not sent to HubSpot, or None when they are.

    WHY `str.rpartition` and no pattern: in production `submitted_by` is the email Envoy stamps
    after verifying Cloudflare Access, so the only question is whether it has a local part and a
    domain. `internal_emails` must hold lower-case addresses.
    """
    if not submitted_by:
        return "no_submitter"
    local, at, domain = submitted_by.rpartition("@")
    reason: str | None = None
    if not at or not local or not domain:
        reason = "not_an_email"
    elif domain.lower() == INTERNAL_DOMAIN or submitted_by.lower() in internal_emails:
        reason = "internal"
    return reason


def entry_url(base_url: str, benchmark_id: str, spec_id: str) -> str:
    """The public page of one submission (the board's "spec" page)."""
    return (
        f"{base_url.rstrip('/')}/spec.html?benchmark={quote(benchmark_id, safe='')}"
        f"&spec={quote(spec_id, safe='')}"
    )


def target_for(submissions: Sequence[Submission], stages: Stages, base_url: str) -> Target:
    """The card one submitter should have.

    INVARIANT: a submission is a distinct (board, recipe) pair. A rerun of the same recipe on the
    same board counts once; the same recipe on another board is real new work and counts again.
    """
    if not submissions:
        msg = "a target needs at least one submission"
        raise ValueError(msg)
    pairs = {(s.benchmark_id, s.spec_id) for s in submissions}
    newest = max(submissions, key=lambda s: s.submitted_at)
    qualifying = sorted((s for s in submissions if s.sota_qualified), key=lambda s: s.submitted_at)
    stage = stages.submissions[min(len(pairs), len(stages.submissions)) - 1]
    return Target(
        submission_count=len(pairs),
        stage_id=stage,
        entry_url=entry_url(base_url, newest.benchmark_id, newest.spec_id),
        last_active=newest.submitted_at.date(),
        sota_entry_url=(
            entry_url(base_url, qualifying[0].benchmark_id, qualifying[0].spec_id)
            if qualifying
            else None
        ),
    )


def _write_if_changed(changes: dict[str, str], card: CardState, prop: str, value: str) -> None:
    if prop in card.hand_set or card.values.get(prop) == value:
        return
    changes[prop] = value


def card_changes(card: CardState, target: Target, stages: Stages) -> dict[str, str] | None:
    """The properties to write on an existing card; None means leave the card entirely alone.

    INVARIANT: a card only moves forward, and only from a stage the sync owns. Dropped out is the
    team's call and is never touched, fields included (Filip, 2026-11-19).
    """
    if card.stage_id == stages.dropped_out:
        return None
    changes: dict[str, str] = {}
    order = stages.movable
    if card.stage_id in order and order.index(target.stage_id) > order.index(card.stage_id):
        changes[PROP_STAGE] = target.stage_id
    _write_if_changed(changes, card, PROP_COUNT, str(target.submission_count))
    _write_if_changed(changes, card, PROP_ENTRY, target.entry_url)
    # INVARIANT: the SOTA flag is set once and never cleared or moved to a later entry; a value a
    # person set on either field wins.
    sota_untouched = PROP_SOTA not in card.hand_set and PROP_SOTA_ENTRY not in card.hand_set
    if target.sota_entry_url and card.values.get(PROP_SOTA) != "true" and sota_untouched:
        changes[PROP_SOTA] = "true"
        changes[PROP_SOTA_ENTRY] = target.sota_entry_url
    return changes


def new_card_properties(target: Target, *, name: str) -> dict[str, str]:
    """A new card's properties; the adapter adds the pipeline."""
    properties = {
        "dealname": name,
        PROP_STAGE: target.stage_id,
        PROP_COUNT: str(target.submission_count),
        PROP_ENTRY: target.entry_url,
    }
    if target.sota_entry_url:
        properties[PROP_SOTA] = "true"
        properties[PROP_SOTA_ENTRY] = target.sota_entry_url
    return properties


def card_name(first: str | None, last: str | None, email: str) -> str:
    """Name a new card like the existing ones ("<first> <last>"), or by email without a name."""
    parts = [part.strip() for part in (first, last) if part and part.strip()]
    if not parts or parts == [UNKNOWN_NAME]:
        return email
    return " ".join(parts)


def last_active_to_write(stored: date | None, newest: date) -> date | None:
    """The contact's 😱 Last Active Date to write, or None. It only ever moves forward."""
    if stored is not None and stored >= newest:
        return None
    return newest
