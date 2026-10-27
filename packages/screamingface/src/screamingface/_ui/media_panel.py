"""A Case's pictures and files, opened in place in the report browser: Show picture or Save file."""

from __future__ import annotations

import base64
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.media import CaseMedia, FetchedMedia

#: Picture types drawn in place as an ``<img>``. WHY only these: they are the four the importer
#: accepts, and a browser draws each from a ``data:`` URI; any other picture is saved instead.
_IN_PLACE_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_QUESTION_OPEN = "<div class='sf-pane__q'>"
#: WHY loud: the button is the only way to see a Case's picture, so it is the one filled, accent
#: button in the card, at least 28px tall, with an icon that says "picture" before the words do.
MEDIA_STYLE = """<style>
.sf-report-browser .sf-media-open{display:inline-flex;align-items:center;min-height:28px;
 padding:3px 12px;margin:2px 8px 2px 0;border:1px solid var(--sf-accent);border-radius:4px;
 background:var(--sf-accent);color:var(--sf-accent-contrast);font:inherit;font-size:13px;
 font-weight:600;line-height:1.2;cursor:pointer;vertical-align:middle}
.sf-report-browser .sf-media-open:hover{background:var(--sf-accent-hover);
 border-color:var(--sf-accent-hover)}
.sf-report-browser .sf-media-open:focus-visible{outline:2px solid var(--sf-ink);outline-offset:2px}
.sf-report-browser .sf-media-img{display:block;max-width:100%;margin:6px 0;
 border:1px solid var(--sf-line)}
</style>"""
_QUESTION_CLOSE = "</div>"


class MediaPanel:
    """Turn each placeholder line in a Case card into its button, and open what is clicked.

    FEATURE (OME-1271): a Case Result shows each picture as a placeholder line. In the browser
    that line gets **Show picture** (fetched, checked, then drawn in place of the button) or,
    for a file, **Save file** (fetched, checked, written into ``folder``, its path shown in
    ``notice``), because a notebook can draw a picture but not a PDF.

    Stage 1 — ``page`` then ``mark`` run while a page renders: each placeholder line in a
        card's question gets a button whose element id is remembered with its item.
    Stage 2 — ``on_click`` gets a click on that id and ``open`` fetches and checks the item: a
        picture is kept as a ``data:`` URI, a file is saved.
    Stage 3 — ``redraw`` renders the page again, and ``mark`` now draws a kept picture above
        its line.

    e.g. ``user: image/jpeg · 1.9 MB · sha256 3fcd47b9…`` → ``user: [Show picture] image/jpeg ·
    1.9 MB · sha256 3fcd47b9…`` → after the click, the figure itself above that line.
    """

    def __init__(
        self,
        widgets: Any,
        *,
        folder: Path,
        redraw: Callable[[], None],
    ) -> None:
        self.folder: Path = folder
        self._redraw: Callable[[], None] = redraw
        # WHY by element id: ipyevents reports only the clicked element's id.
        self._targets: dict[str, CaseMedia] = {}
        # WHY by sha256: the same picture opened once shows on every Case and page that has it.
        self._kept: dict[str, str] = {}
        self.notice = widgets.HTML()
        self.notice.add_class("sf-case-media")

    def page(self, click_handler: str = "") -> Callable[[str, CaseResult], str]:
        """Start drawing a page: forget the last page's buttons, and return what marks each pane.

        WHY forget: the page drawn last is the one on screen, so only its buttons can be clicked.
        """

        self._targets = {}
        return lambda pane, case: self.mark(pane, case, click_handler)

    def mark(self, pane: str, case: CaseResult, click_handler: str = "") -> str:
        """``pane`` with each placeholder line of its question turned into a button or picture.

        Each button sits where its picture sits in the message, first, last or between texts. A
        picture whose line the card cut off (a question longer than the clip budget) gets its
        button at the top of the question instead, so no picture is out of reach.

        e.g. MMMU's ``Which graph… <image 1>`` then the picture → the button after the text;
        a 12,000-character HLE question then its picture → the button first, with its line.
        """

        start: int = pane.find(_QUESTION_OPEN)
        end: int = pane.find(_QUESTION_CLOSE, start)
        if start < 0 or end < 0:
            return pane
        question: str = pane[start + len(_QUESTION_OPEN) : end]
        cursor: int = 0
        cut_off: list[str] = []
        for item in case.media:
            line: str = escape(str(item))
            found: int = question.find(line, cursor)
            control: str = self._control(item, click_handler)
            if found < 0:
                cut_off.append(f"{control}{line}\n")
                continue
            question = question[:found] + control + question[found:]
            cursor = found + len(control) + len(line)
        return pane[:start] + _QUESTION_OPEN + "".join(cut_off) + question + pane[end:]

    def on_click(self, event: dict) -> None:
        """Open the item whose button was clicked, then draw the page again; ignore other clicks.

        WHY ignore: ipyevents reports every click in the cases page, most of them on Cases.
        """

        target: object = event.get("target", {}).get("id", "")
        item: CaseMedia | None = self._targets.get(target) if isinstance(target, str) else None
        if item is not None:
            self.open(item)
            self._redraw()

    def open(self, item: CaseMedia) -> None:
        """Fetch ``item``: keep a picture to draw, or save a file and say where it went."""

        # WHY a notice first: a 2 MB picture can take a few seconds, and a click with no answer
        # reads as a broken button.
        self.notice.value = f"<p>Loading {escape(str(item))}…</p>"
        try:
            # WHY imported here: the process-wide Client is built on first use, not on import.
            from screamingface._default_client import fetch_media

            fetched: FetchedMedia = fetch_media(item)
            if _draws_in_place(item):
                encoded: str = base64.b64encode(fetched.data).decode("ascii")
                self._kept[item.sha256] = f"data:{item.media_type};base64,{encoded}"
                self.notice.value = ""
            else:
                # WHY the full path: the browser's folder may not exist yet, and ``save`` reads a
                # path that isn't a folder as the file to write.
                saved: Path = fetched.save(self.folder / item.default_name)
                self.notice.value = f"<p>Saved to {escape(str(saved))}</p>"
        except (OSError, ScreamingFaceError) as exc:
            reason: str = exc.user_message if isinstance(exc, ScreamingFaceError) else str(exc)
            self.notice.value = f'<p role="alert">{escape(reason)}</p>'

    def _control(self, item: CaseMedia, click_handler: str) -> str:
        """The kept picture, or the button that opens ``item``, to sit before its line."""

        kept: str | None = self._kept.get(item.sha256)
        if kept is not None:
            return f"<img class='sf-media-img' src='{kept}' alt='{escape(str(item))}'>"
        target: str = f"sf-media-{uuid4().hex}"
        self._targets[target] = item
        # WHY no inner element: ipyevents reports the innermost clicked element, and only the
        # button carries the id.
        label: str = "🖼 Show picture" if _draws_in_place(item) else "📄 Save file"
        onclick: str = f' onclick="{escape(click_handler, quote=True)}"' if click_handler else ""
        return (
            f"<button type='button' class='sf-media-open' id='{target}' "
            f"title='{escape(str(item))}'{onclick}>{label}</button> "
        )


def _draws_in_place(item: CaseMedia) -> bool:
    """Whether ``item`` is a picture a browser draws from a ``data:`` URI."""

    return item.kind == "image" and item.media_type in _IN_PLACE_TYPES
