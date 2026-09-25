"""The open share of the cost/score Pareto frontier (OME-1145, contract from OME-1179).

FEATURE: the "N% open" card on a benchmark page: of the entries the table marks as best score for
the money, how many can someone else run end to end on downloadable weights.

Pure functions, no I/O. The route supplies the ranked table's own inputs, so the card and the
table's Pareto marks are one definition (D-L).

WHY this replaced OME-323's statistic: that one counted every row, Baselines included, across
every benchmark revision, and traced a score-only "who holds the top" trend. The owner superseded
it on 2026-09-10 (D-L, D-N): the frontier is cost/score, the unit is the entry (D1), and the trend
is the open share over time.

AIDEV-NOTE: the frontier itself comes from `pareto.py`, never re-derived here. Two copies of the
domination rule would drift, and the card would then disagree with the table's marks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from scoreboard.classification.openness import Openness, classify_entry

from .pareto import ParetoEntry, compute_pareto_frontier_ids
from .schemas import FrontierPoint, FrontierResult

# D-T (owner, 2026-09-25): the routes are already public in `url4_expression`; the cap only bounds
# the response when a registry is badly out of date.
MAX_UNRECOGNISED_MODELS = 20


@dataclass(frozen=True)
class HistoryRow:
    """One comparable submission, for replaying the frontier as it stood over time."""

    source_id: str
    spec_id: str
    score: float
    run_cost_usd: Decimal | None
    submitted_at: datetime


@dataclass(frozen=True)
class FrontierMember:
    """What classifying one frontier entry needs, and nothing else (OME-1179 constraint 4)."""

    source_id: str
    models: tuple[str, ...] | None
    openness_override: Openness | None


@dataclass(frozen=True)
class _Split:
    open_count: int
    closed_count: int
    unidentified_count: int
    unrecognised: frozenset[str]

    @property
    def open_share(self) -> float | None:
        classified = self.open_count + self.closed_count
        return self.open_count / classified if classified else None


def _split(ids: frozenset[str], members: Mapping[str, FrontierMember]) -> _Split:
    open_count = closed_count = unidentified_count = 0
    unrecognised: set[str] = set()
    for source_id in ids:
        member = members.get(source_id)
        # A frontier row the models read did not return (deleted between the two reads) says
        # nothing about what it ran: unidentified, never guessed.
        verdict, unknown = (
            classify_entry(member.models, member.openness_override)
            if member is not None
            else ("unidentified", ())
        )
        unrecognised.update(unknown)
        if verdict == "open":
            open_count += 1
        elif verdict == "closed":
            closed_count += 1
        else:
            unidentified_count += 1
    return _Split(open_count, closed_count, unidentified_count, frozenset(unrecognised))


def _replay(history: Sequence[HistoryRow]) -> list[tuple[datetime, frozenset[str]]]:
    """The frontier after each submission, in submission order.

    INVARIANT: best-per-spec exactly as the ranked query collapses it: highest score wins, and on
    a tie the newer row (`store._build_leaderboard_query`'s `score DESC, submitted_at DESC`). A
    spec that improved must not count twice on a historical frontier.

    AIDEV-NOTE: O(n * m log m) for n submissions over m specs, recomputing the frontier from
    scratch each step. Right at today's scale (tens of rows per board); a board with thousands
    of submissions wants an incremental sweep. Not built speculatively.
    """
    best: dict[str, HistoryRow] = {}
    steps: list[tuple[datetime, frozenset[str]]] = []
    for row in sorted(history, key=lambda r: (r.submitted_at, r.source_id)):
        held = best.get(row.spec_id)
        if held is None or row.score >= held.score:
            best[row.spec_id] = row
        frontier = compute_pareto_frontier_ids(
            [
                # The revision is fixed by the history read (registered revision only), so one
                # cohort: the same thing `leaderboard_pareto_inputs` hands the table.
                ParetoEntry(r.source_id, r.spec_id, None, r.score, r.run_cost_usd)
                for r in best.values()
            ]
        )
        steps.append((row.submitted_at, frontier))
    return steps


def frontier_member_ids(
    current: Sequence[ParetoEntry], history: Sequence[HistoryRow], *, pinned: bool
) -> frozenset[str]:
    """Every row that is, or ever was, on the frontier: the only rows whose models are read."""
    if not pinned:
        return frozenset()
    ids = set(compute_pareto_frontier_ids(current))
    for _, frontier in _replay(history):
        ids |= frontier
    return frozenset(ids)


def _trend(
    history: Sequence[HistoryRow], members: Mapping[str, FrontierMember]
) -> list[FrontierPoint]:
    """A point each time a submission changes the frontier's open share (D-L)."""
    points: list[FrontierPoint] = []
    last: float | None = None
    for at, frontier in _replay(history):
        split = _split(frontier, members)
        share = split.open_share
        if share == last and (points or share is None):
            continue
        points.append(
            FrontierPoint(
                at=at,
                open_share=share,
                open_count=split.open_count,
                closed_count=split.closed_count,
            )
        )
        last = share
    return points


def compute_frontier_openness(
    current: Sequence[ParetoEntry],
    history: Sequence[HistoryRow],
    members: Mapping[str, FrontierMember],
    *,
    pinned: bool,
) -> FrontierResult:
    """The open share of the full-board Pareto frontier, and its trend.

    ``current`` is exactly what the table's marks are computed from
    (`leaderboard_pareto_inputs`); ``history`` is every comparable submission for the trend;
    ``members`` holds the models of every row in `frontier_member_ids`.

    INVARIANT (D12): ``pinned`` false means the board has no registered revision, and the table
    makes no frontier claim. Nor does this: `frontier_available` false and no share.
    """
    if not pinned:
        return FrontierResult(
            frontier_available=False,
            frontier_size=0,
            open_count=0,
            closed_count=0,
            unidentified_count=0,
            unrecognised_models=[],
            open_share=None,
            trend=[],
        )
    frontier = compute_pareto_frontier_ids(current)
    split = _split(frontier, members)
    return FrontierResult(
        frontier_available=True,
        frontier_size=len(frontier),
        open_count=split.open_count,
        closed_count=split.closed_count,
        unidentified_count=split.unidentified_count,
        unrecognised_models=sorted(split.unrecognised)[:MAX_UNRECOGNISED_MODELS],
        open_share=split.open_share,
        trend=_trend(history, members),
    )
