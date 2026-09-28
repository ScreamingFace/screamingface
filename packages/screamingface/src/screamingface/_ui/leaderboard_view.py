"""Escaped SFDS rich displays for public Leaderboard values."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from html import escape
from typing import overload

from screamingface._ui.leaderboard_style import LEADERBOARD_STYLE
from screamingface._ui.report_view import _score_text
from screamingface._ui.style import NO_MATH
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardEntry,
    LeaderboardInfo,
)
from screamingface.url4 import Url4


class LeaderboardCatalog(Sequence[LeaderboardInfo]):
    """Immutable Leaderboard catalogue with a filterable notebook representation."""

    __slots__ = ("_values",)

    def __init__(self, values: Sequence[LeaderboardInfo]) -> None:
        self._values = tuple(values)

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[LeaderboardInfo]:
        return iter(self._values)

    @overload
    def __getitem__(self, index: int) -> LeaderboardInfo: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[LeaderboardInfo, ...]: ...

    def __getitem__(self, index: int | slice) -> LeaderboardInfo | tuple[LeaderboardInfo, ...]:
        return self._values[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LeaderboardCatalog):
            return self._values == other._values
        if isinstance(other, tuple):
            return self._values == other
        return False

    def __repr__(self) -> str:
        return f"Leaderboards({len(self)})"

    def _repr_html_(self) -> str:
        return leaderboard_catalog_html(self._values)


@dataclass(frozen=True, slots=True)
class _DisplayRow:
    name: str
    kind: str
    score: float
    questions: int | None
    # AIDEV-NOTE: UNUSED since OME-832. Its readers were the data-verified attribute
    # and the `verified` chip, both removed because verified_by_screamingface asserts
    # nothing (OME-820). `_candidate_row` still populates it, so nothing in ruff,
    # pyright or coverage will notice it going stale. Parked deliberately for OME-821,
    # which gives the flag a real signal and restores both readers. Do NOT key new
    # presentation on it before then — a row's value says nothing today, and doing so
    # would reintroduce the inert trust signal this change removed.
    verified: bool | None
    python_source: str | None
    source_url: str | None


def leaderboard_catalog_html(values: Sequence[LeaderboardInfo]) -> str:
    """Render registered Leaderboards as a filterable SFDS list widget."""

    rows = "".join(_catalog_row(value) for value in values)
    if not rows:
        rows = "<div class='sf-lb__empty'>No Leaderboards are registered.</div>"
    count = f"{len(values)} benchmark{'s' if len(values) != 1 else ''}"
    filter_action = (
        "const q=this.value.toLowerCase();"
        "this.closest('.sf-lb').querySelectorAll('[data-sf-search]').forEach((row)=>{"
        "row.hidden=!row.dataset.sfSearch.includes(q)})"
    )
    return (
        f"{LEADERBOARD_STYLE}<div class='sf-lb sf-lb-list {NO_MATH}' "
        "aria-label='ScreamingFace Leaderboards'>"
        "<div class='sf-lb-list__head'><h3 class='sf-lb__title'>Leaderboards</h3>"
        f"<span class='sf-lb-list__count'>{count}</span></div>"
        "<label class='sf-lb-list__filter'><span class='sf-lb-list__filter-label'>filter:</span>"
        f"<input type='search' placeholder='Filter leaderboards…' oninput=\"{filter_action}\" "
        "aria-label='Filter Leaderboards'></label>"
        f"<div class='sf-lb-list__rows'>{rows}</div>"
        "<div class='sf-lb__foot'>"
        "<span class='sf-lb__tag'>.get(id)</span> → ranked candidates and imported baselines"
        "</div></div>"
    )


def leaderboard_html(board: Leaderboard) -> str:
    """Render one candidate Leaderboard with sourced single-Model baselines."""

    values = _display_rows(board)
    rows = _board_rows(values)
    if not rows:
        rows = "<div class='sf-lb__empty'>No scores have been published yet.</div>"
    title = escape(board.benchmark.display_name)
    benchmark_id = escape(board.benchmark.id)
    return (
        f"{LEADERBOARD_STYLE}<div class='sf-lb sf-lb-board {NO_MATH}' "
        f"aria-label='ScreamingFace candidate leaderboard for {title}'>"
        "<div class='sf-lb__head'><h3 class='sf-lb__title'>Leaderboard</h3>"
        "<div class='sf-lb__controls'><span class='sf-lb__field'>"
        "<span class='sf-lb__field-label'>benchmark:</span>"
        f"<span class='sf-lb__field-value'>{title}</span></span>"
        # OME-832: the "verified only" checkbox lived here. Removed, not relabelled —
        # verified_by_screamingface CERTIFIES NOTHING whatever it holds: nothing re-runs
        # submissions (OME-414) and nothing attests where a run executed.
        #
        # WHY that is a reason to delete the control rather than leave it: the value is
        # NOT uniform. OME-820 forbids a backfill, so rows predating it keep false while
        # newer rows are true. A filter would therefore partition rows by whether they
        # predate the default change, while presenting itself as a verification filter —
        # measuring submission date and reading as though it measured trust. That is
        # worse than filtering nothing, which is why relabelling could not have fixed it.
        #
        # OME-821 restores the control once the flag means something (OME-841 corrected
        # this note, which previously said the field was "uniform" — it is not, and that
        # wording argued for the opposite conclusion to the one this code took).
        "</div></div>"
        "<div class='sf-lb__table' role='table'>"
        "<div class='sf-lb__row sf-lb__row--head' role='row'>"
        "<span role='columnheader'>#</span><span role='columnheader'>entry</span>"
        "<span class='sf-lb__kind' role='columnheader'>kind</span>"
        "<span class='sf-lb__sort' role='columnheader'>score ↓</span>"
        "<span class='sf-lb__questions' role='columnheader'>questions</span>"
        "<span role='columnheader'>action</span></div>"
        f"{rows}</div><div class='sf-lb__foot'><span class='sf-lb__tag'>fork</span>"
        f" copies editable Python · <span class='sf-lb__tag'>{benchmark_id}</span>"
        " identifies this benchmark</div></div>"
    )


def _catalog_row(value: LeaderboardInfo) -> str:
    description = escape(value.description or "No description published.")
    search = escape(
        f"{value.id} {value.display_name} {value.description or ''}".casefold(),
        quote=True,
    )
    identifier = escape(value.id)
    call = escape(f'sf.leaderboards.get("{value.id}")')
    return (
        f"<div class='sf-lb-list__row' data-sf-search='{search}'>"
        "<div><div class='sf-lb-list__name'>"
        f"{escape(value.display_name)}</div>"
        f"<div class='sf-lb-list__description'>{description}</div>"
        f"<div class='sf-lb-list__call'>{call}</div></div>"
        f"<div class='sf-lb-list__meta'><span class='sf-lb__chip'>{identifier}</span>"
        f"<time datetime='{value.created_at.date().isoformat()}'>"
        f"{value.created_at.date().isoformat()}</time></div></div>"
    )


def _display_rows(board: Leaderboard) -> tuple[_DisplayRow, ...]:
    candidates = tuple(_candidate_row(value) for value in board.entries)
    baselines = tuple(_baseline_row(value) for value in board.baselines)
    return tuple(sorted((*candidates, *baselines), key=lambda row: row.score, reverse=True))


def _candidate_row(value: LeaderboardEntry) -> _DisplayRow:
    return _DisplayRow(
        name=value.spec_id,
        kind="candidate",
        score=value.score,
        questions=value.total_questions,
        verified=value.verified_by_screamingface,
        python_source=_fork_source(value.url4),
        source_url=None,
    )


def _baseline_row(value: LeaderboardBaseline) -> _DisplayRow:
    return _DisplayRow(
        name=value.model_name,
        kind="single",
        score=value.score,
        questions=None,
        verified=None,
        python_source=None,
        source_url=value.source_url,
    )


def _board_rows(values: Sequence[_DisplayRow]) -> str:
    # INVARIANT (OME-866): scores are benchmark-native, so the bar origin cannot be
    # assumed to be 0 — HealthBench worst-30 is negative for every serious entry. The
    # floor is min(0, lowest on screen): a classic 0..1 board keeps its absolute zero
    # origin, a negative board shifts the origin down instead of emitting negative CSS
    # widths. A degenerate span renders empty tracks rather than dividing.
    maximum = max((value.score for value in values), default=0.0)
    floor = min(0.0, min((value.score for value in values), default=0.0))
    span = maximum - floor
    return "".join(
        _board_row(value, rank, floor, span) for rank, value in enumerate(values, start=1)
    )


def _board_row(value: _DisplayRow, rank: int, floor: float, span: float) -> str:
    winner = rank == 1
    classes = "sf-lb__row" + (" sf-lb__row--winner" if winner else "")
    # OME-832: data-verified is no longer emitted. Its only reader was the removed
    # "verified only" filter handler; nothing else in the package consumes it.
    chip = _row_chip(value)
    fill_class = "sf-lb__score-fill"
    if winner:
        fill_class += (
            " sf-lb__score-fill--gradient"
            if value.python_source is not None
            else " sf-lb__score-fill--accent"
        )
    width = max(0.0, min(100.0, (value.score - floor) / span * 100)) if span > 0 else 0.0
    questions = "—" if value.questions is None else str(value.questions)
    icon = "😱" if value.python_source is not None else "●"
    return (
        f"<div class='{classes}' role='row'>"
        f"<span class='sf-lb__rank' role='cell'>{rank}</span>"
        "<span class='sf-lb__entry' role='cell'>"
        f"<span class='sf-lb__icon' aria-hidden='true'>{icon}</span>"
        f"<span class='sf-lb__entry-name'>{escape(value.name)}</span>{chip}</span>"
        f"<span class='sf-lb__kind' role='cell'>{value.kind}</span>"
        "<span class='sf-lb__score' role='cell'>"
        f"<span class='sf-lb__score-number'>{_score_text(value.score)}</span>"
        f"<span class='sf-lb__score-track'><span class='{fill_class}' "
        f"style='width:{width:.1f}%'></span></span></span>"
        f"<span class='sf-lb__questions' role='cell'>{questions}</span>"
        f"<span class='sf-lb__action' role='cell'>{_row_action(value)}</span></div>"
    )


def _row_chip(value: _DisplayRow) -> str:
    """The baseline chip, and nothing else.

    INVARIANT: only an imported single-Model row may wear this chip. The predicate is
    `kind`, NOT `python_source is None` — `_baseline_row` sets kind="single" and
    `_candidate_row` sets kind="candidate", whereas forkability is a property of the
    url4 expression and says nothing about where a row came from.

    WHY that matters: this used to read `if value.verified: … ; if value.python_source is
    None: baseline`. The verified branch was removed in OME-832 because the flag asserts
    nothing (OME-820). Deleting it alone would have let a candidate with an unforkable
    url4 fall through and be labelled "baseline" — presenting a community submission as
    an imported reference, a worse error than the one being fixed. It already did that
    for *unverified* such candidates, which this also fixes.
    """
    if value.kind == "single":
        return "<span class='sf-lb__chip'>baseline</span>"
    return ""


def _row_action(value: _DisplayRow) -> str:
    if value.python_source is not None:
        python_source = escape(value.python_source, quote=True)
        action = (
            "navigator.clipboard.writeText(this.dataset.python);this.textContent='copied';"
            "setTimeout(()=>this.textContent='fork',1200)"
        )
        return (
            f"<button class='sf-lb__button' type='button' data-python=\"{python_source}\" "
            f'onclick="{action}">fork</button>'
        )
    if value.source_url is not None:
        return (
            f"<a class='sf-lb__source' href='{escape(value.source_url, quote=True)}' "
            "target='_blank' rel='noopener noreferrer'>source</a>"
        )
    return "—"


def _fork_source(value: Url4) -> str | None:
    try:
        return value.to_python()
    except ValueError:
        return None


__all__: list[str] = []
