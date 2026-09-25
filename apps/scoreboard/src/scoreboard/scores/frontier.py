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
from datetime import UTC, date, datetime
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


_Verdict = tuple[str, tuple[str, ...]]


def _verdicts(members: Mapping[str, FrontierMember]) -> dict[str, _Verdict]:
    """Classify every member ONCE (review round 1, 2026-09-26).

    WHY: the trend visits the same members at every step. Classifying per visit repeated the
    work and logged each unrecognised route once per step, a log flood a crafted board could
    drive. Each member is now classified, and logged, once per request.
    """
    return {
        source_id: classify_entry(member.models, member.openness_override)
        for source_id, member in members.items()
    }


def _split(ids: frozenset[str], verdicts: Mapping[str, _Verdict]) -> _Split:
    open_count = closed_count = unidentified_count = 0
    unrecognised: set[str] = set()
    for source_id in ids:
        # A frontier row the models read did not return says nothing about what it ran:
        # unidentified, never guessed.
        verdict, unknown = verdicts.get(source_id, ("unidentified", ()))
        unrecognised.update(unknown)
        if verdict == "open":
            open_count += 1
        elif verdict == "closed":
            closed_count += 1
        else:
            unidentified_count += 1
    return _Split(open_count, closed_count, unidentified_count, frozenset(unrecognised))


@dataclass(frozen=True)
class FrontierReplay:
    """The frontier as it stood at the end of each UTC day that had submissions.

    Built once per request by `replay_frontier` and shared by `frontier_member_ids` and the trend.

    WHY daily (review round 1, owner 2026-09-26): the first version recomputed the whole frontier
    after EVERY submission, on a public endpoint, twice per request. With spec ids client-chosen,
    every row can stay non-dominated, so the cost was O(n * m log m): 2,000 crafted rows took about
    7 s per request before any database work. Recomputing once per day with submissions costs
    O(days * m log m). A burst of any size within one day is one step, and a submitter cannot
    create days.
    """

    steps: tuple[tuple[datetime, frozenset[str]], ...]

    @property
    def member_ids(self) -> frozenset[str]:
        ids: set[str] = set()
        for _, frontier in self.steps:
            ids |= frontier
        return frozenset(ids)


def replay_frontier(history: Sequence[HistoryRow]) -> FrontierReplay:
    """Replay ``history`` in submission order, one frontier per UTC day.

    INVARIANT: best-per-spec exactly as the ranked query collapses it: highest score wins, and on
    a tie the newer row (`store._build_leaderboard_query`'s `score DESC, submitted_at DESC`). A
    spec that improved must not count twice on a historical frontier.

    Each step is stamped with the last submission of its day, a real event time.
    """
    best: dict[str, HistoryRow] = {}
    steps: list[tuple[datetime, frozenset[str]]] = []
    ordered = sorted(history, key=lambda r: (r.submitted_at, r.source_id))
    for index, row in enumerate(ordered):
        held = best.get(row.spec_id)
        if held is None or row.score >= held.score:
            best[row.spec_id] = row
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if following is not None and _day(following.submitted_at) == _day(row.submitted_at):
            continue
        frontier = compute_pareto_frontier_ids(
            [
                # The revision is fixed by the history read (registered revision only), so one
                # cohort: the same thing `leaderboard_pareto_inputs` hands the table.
                ParetoEntry(r.source_id, r.spec_id, None, r.score, r.run_cost_usd)
                for r in best.values()
            ]
        )
        steps.append((row.submitted_at, frontier))
    return FrontierReplay(tuple(steps))


def _day(at: datetime) -> date:
    return at.astimezone(UTC).date()


def frontier_member_ids(
    current: Sequence[ParetoEntry], replay: FrontierReplay, *, pinned: bool
) -> frozenset[str]:
    """Every row that is, or ever was, on the frontier: the only rows whose models are read."""
    if not pinned:
        return frozenset()
    return frozenset(compute_pareto_frontier_ids(current)) | replay.member_ids


def _trend(replay: FrontierReplay, verdicts: Mapping[str, _Verdict]) -> list[FrontierPoint]:
    """A point each day the frontier's open share changed (D-L, daily since review round 1)."""
    points: list[FrontierPoint] = []
    last: float | None = None
    for at, frontier in replay.steps:
        split = _split(frontier, verdicts)
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
    replay: FrontierReplay,
    members: Mapping[str, FrontierMember],
    *,
    pinned: bool,
) -> FrontierResult:
    """The open share of the full-board Pareto frontier, and its trend.

    ``current`` is exactly what the table's marks are computed from
    (`leaderboard_pareto_inputs`); ``replay`` is `replay_frontier` over every comparable
    submission; ``members`` holds the models of every row in `frontier_member_ids`.

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
    verdicts = _verdicts(members)
    split = _split(frontier, verdicts)
    return FrontierResult(
        frontier_available=True,
        frontier_size=len(frontier),
        open_count=split.open_count,
        closed_count=split.closed_count,
        unidentified_count=split.unidentified_count,
        unrecognised_models=sorted(split.unrecognised)[:MAX_UNRECOGNISED_MODELS],
        open_share=split.open_share,
        trend=_trend(replay, verdicts),
    )
