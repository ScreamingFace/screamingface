"""The focused Case's pictures and files in the report browser: Show picture, or Save file."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.media import CaseMedia, FetchedMedia


class MediaPanel:
    """One row per picture or file of the focused Case, each with the button its kind needs.

    FEATURE (OME-1271): a Case Result shows each picture as a placeholder line. Here a picture
    gets **Show picture** (fetched, checked, shown under the Case) and a file gets **Save file**
    (fetched, checked, written into ``folder``, its path shown), because a notebook can show a
    picture inline but not a PDF.
    """

    def __init__(
        self,
        widgets: Any,
        *,
        folder: Path,
        fetch: Callable[[CaseMedia], FetchedMedia] | None = None,
    ) -> None:
        self.w = widgets
        self.folder: Path = folder
        # WHY injectable: the default is the process-wide Client, which the browser's tests
        # must not reach over the network.
        self._fetch: Callable[[CaseMedia], FetchedMedia] | None = fetch
        self._shown: tuple[str, ...] | None = None
        self.rows = widgets.VBox()
        self.notice = widgets.HTML()
        self.picture = widgets.Box()
        self.widget = widgets.VBox([self.rows, self.notice, self.picture])
        self.widget.add_class("sf-case-media")

    def show(self, case: CaseResult | None) -> None:
        """List ``case``'s pictures and files; the panel is empty for a text Case or no Case."""

        media: tuple[CaseMedia, ...] = () if case is None else case.media
        shown: tuple[str, ...] = tuple(item.sha256 for item in media)
        if shown == self._shown:
            return
        self._shown = shown
        self.notice.value = ""
        self.picture.children = ()
        self.rows.children = tuple(self._row(item) for item in media)

    def _row(self, item: CaseMedia) -> Any:
        """One item's button and its placeholder line."""

        button = self.w.Button(
            description="Show picture" if item.kind == "image" else "Save file",
            tooltip=str(item),
            layout=self.w.Layout(width="120px"),
        )
        button.on_click(lambda _, item=item, button=button: self._open(item, button))
        return self.w.HBox([button, self.w.Label(value=str(item))])

    def _open(self, item: CaseMedia, button: Any) -> None:
        """Fetch ``item``; show a picture under the Case, or save a file and show its path."""

        button.disabled = True
        self.notice.value = ""
        try:
            fetched: FetchedMedia = self._fetcher()(item)
            if item.kind == "image":
                self.picture.children = (
                    self.w.Image(value=fetched.data, format=item.media_type.partition("/")[2]),
                )
            else:
                saved: Path = fetched.save(self.folder)
                self.notice.value = f"<p>Saved to {escape(str(saved))}</p>"
        except (OSError, ScreamingFaceError) as exc:
            reason: str = exc.user_message if isinstance(exc, ScreamingFaceError) else str(exc)
            self.notice.value = f'<p role="alert">{escape(reason)}</p>'
        finally:
            button.disabled = False

    def _fetcher(self) -> Callable[[CaseMedia], FetchedMedia]:
        """The injected fetch, or the process-wide Client's."""

        if self._fetch is not None:
            return self._fetch
        from screamingface._default_client import fetch_media

        return fetch_media
