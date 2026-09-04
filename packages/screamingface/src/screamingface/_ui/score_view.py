"""Notebook rendering for a published LeaderboardScore (what `submit()` displays)."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING
from urllib.parse import quote

# WHY private imports from report_view: the score card is the Report panel's sibling —
# same tokens, same grid, same disclosure — and duplicating that CSS here is how two
# cards drift apart. One stylesheet, two renderers.
from screamingface._ui.report_view import _STYLE, _cell, _clip, _score_text, _stamp

if TYPE_CHECKING:
    from screamingface.leaderboard import LeaderboardScore


def leaderboard_score_html(value: LeaderboardScore) -> str:
    """Render one published score as a brand card.

    Mental model: the receipt for a publication — what board it landed on, the exact
    number the Engine graded (never reformatted), who it is attributed to, and the
    folded URL4 recipe anyone can copy to re-run the claim.

    Stages: (1) head — title plus the Leaderboard it landed on; (2) strip — the
    identity line (benchmark, revision when the submission carried one, timestamp,
    and the persisted score id); (3) figure grid — score is the hero cell, rendered
    as a plain benchmark-native number (HealthBench worst-30 is negative; a ×100 or
    percent rendering here would be wrong, OME-866); (4) the URL4 expression behind
    a disclosure, because it is enormous and identity, not reading matter.
    """

    revision = _revision(value)
    identity = str(value.benchmark_id) + (f" · rev {revision}" if revision else "")
    questions = f"{value.total_questions} question" + ("" if value.total_questions == 1 else "s")
    receipt = " · ".join((questions, f"id {str(value.id)[:8]}…"))
    authors = ", ".join(value.authors) if value.authors else "—"
    ranking_notice = _ranking_notice_html(value)
    cells = [
        # INVARIANT (OME-866): the score renders as stored — plain number, no ×100,
        # no percent. _score_text is shared with the Report card so the same figure
        # never renders two ways in one notebook.
        _cell("score", _score_text(value.score), score=True),
        _cell("spec", str(value.spec_id)),
        # INVARIANT (OME-1053): ownership and credit are distinct. Keep both visible so the
        # receipt never calls the authenticated submitter an author the caller did not credit.
        _cell("submitter", value.submitted_by or "—"),
        _cell("authors", authors, title=authors),
        _cell("submitted", _stamp(value.submitted_at)),
    ]
    return (
        f"{_STYLE}<div class='sf-ui sf-report' aria-label='ScreamingFace published score'>"
        "<div class='sf-report__head-row'><div>"
        "<div class='sf-report__title'>Score published</div>"
        f"<div class='sf-report__sub'>Leaderboard · {escape(str(value.benchmark_id))}</div>"
        f"</div>{_board_link_html(value)}</div>"
        "<div class='sf-report__strip'>"
        "<span class='sf-report__tick' aria-hidden='true'>&check;</span>"
        f"<span class='sf-report__strip-id'>{escape(identity)}</span>"
        f"<span class='sf-report__strip-when'>{escape(_stamp(value.submitted_at))}</span>"
        f"<span class='sf-report__receipt'>{escape(receipt)}</span></div>"
        "<div class='sf-report__card'>"
        f"{ranking_notice}"
        f"<div class='sf-report__grid'>{''.join(cells)}</div>"
        "<details class='sf-report__det'><summary>URL4</summary>"
        f"<pre class='sf-report__pre'>{escape(_clip(str(value.url4), 1200))}</pre>"
        "</details></div></div>"
    )


def _ranking_notice_html(value: LeaderboardScore) -> str:
    notice = value.ranking_notice
    if notice is None:
        return ""
    submitted = notice.submitted_benchmark_revision or "none reported"
    return (
        "<div class='sf-report__warn' role='alert'>"
        "<strong>Not ranked · benchmark revision mismatch.</strong> "
        f"This run used revision {escape(submitted)}; "
        f"the board ranks revision {escape(notice.registered_benchmark_revision)}."
        "</div>"
    )


def _board_link_html(value: LeaderboardScore) -> str:
    """A deep link to this score's spec page on the Scoreboard it came from.

    The portal is served by the same origin as the API, so the stamped
    ``scoreboard_url`` works unchanged for a local stack (localhost:9106) and the
    deployed Leaderboard. A hand-constructed value has no origin — then no link,
    never a guessed one.
    """
    if value.scoreboard_url is None:
        return ""
    origin = value.scoreboard_url.rstrip("/")
    href = (
        f"{origin}/spec.html"
        f"?benchmark={quote(str(value.benchmark_id), safe='')}"
        f"&spec={quote(str(value.spec_id), safe='')}"
    )
    return (
        f"<a class='sf-report__dl' href='{escape(href, quote=True)}' "
        "target='_blank' rel='noopener noreferrer' "
        "title='Open this spec on the Leaderboard'>View on the Leaderboard &rarr;</a>"
    )


def _revision(value: LeaderboardScore) -> str | None:
    # INVARIANT (OME-909): the mismatch notice carries the store-resolved revision. Prefer it to
    # legacy free-form metadata, which can disagree with the typed submission field and otherwise
    # make one receipt name two different submitted revisions.
    if value.ranking_notice is not None:
        return value.ranking_notice.submitted_benchmark_revision
    if value.metadata is None:
        return None
    candidate = value.metadata.get("benchmark_revision")
    return candidate if isinstance(candidate, str) and candidate else None


__all__ = ["leaderboard_score_html"]
