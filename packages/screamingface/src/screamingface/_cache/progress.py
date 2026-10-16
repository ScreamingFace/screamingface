"""Progress for a community-cache pull: a notebook card or a terminal line (spec decision 14).

The switch follows `evaluate`: `None` shows progress in a notebook or an interactive terminal and
stays quiet when output is piped; `True` / `False` force it on or off. A notebook gets one card
updated in place through an IPython display handle, which every notebook host renders without the
`notebook` extra. A terminal gets one line on stderr, rewritten in place; when stderr is not a
terminal and progress was forced on, it gets a plain line about every tenth of the pull instead.
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, TextIO

if TYPE_CHECKING:
    from screamingface.cache import PullResult

_BAR_WIDTH: Final = 16
_STEPS: Final = 10


@dataclass(frozen=True, slots=True)
class Snapshot:
    origin: str
    rows_read: int
    rows_added: int
    total: int | None
    bytes_received: int
    elapsed_s: float

    @property
    def fraction(self) -> float | None:
        if not self.total:
            return None
        return min(1.0, self.rows_read / self.total)

    @property
    def eta_s(self) -> float | None:
        if not self.total or self.rows_read <= 0 or self.elapsed_s <= 0:
            return None
        rate = self.rows_read / self.elapsed_s
        return max(0.0, (self.total - self.rows_read) / rate)


class Reporter(Protocol):
    def preparing(self, origin: str) -> None: ...

    def update(self, snapshot: Snapshot) -> None: ...

    def finished(self, snapshot: Snapshot, result: PullResult) -> None: ...

    def stopped(self, snapshot: Snapshot, reason: str) -> None: ...


class _Silent:
    def preparing(self, origin: str) -> None:
        return None

    def update(self, snapshot: Snapshot) -> None:
        return None

    def finished(self, snapshot: Snapshot, result: PullResult) -> None:
        return None

    def stopped(self, snapshot: Snapshot, reason: str) -> None:
        return None


class _Terminal:
    def __init__(self, stream: TextIO, *, interactive: bool) -> None:
        self._stream = stream
        self._interactive = interactive
        self._step = -1
        self._width = 0

    def preparing(self, origin: str) -> None:
        self._write(f"community cache  preparing to pull from {origin}…")

    def update(self, snapshot: Snapshot) -> None:
        if not self._interactive:
            step = int((snapshot.fraction or 0.0) * _STEPS)
            if step <= self._step:
                return
            self._step = step
        self._write(f"community cache  {_progress_text(snapshot)}")

    def finished(self, snapshot: Snapshot, result: PullResult) -> None:
        self._write(
            f"community cache  ✓ {result.rows_read:,} rows read · {result.rows_added:,} added · "
            f"{_megabytes(snapshot.bytes_received)} · {_duration(snapshot.elapsed_s)}",
            final=True,
        )

    def stopped(self, snapshot: Snapshot, reason: str) -> None:
        self._write(
            f"community cache  stopped after {snapshot.rows_read:,} rows "
            f"({snapshot.rows_added:,} added): {reason}",
            final=True,
        )

    def _write(self, text: str, *, final: bool = False) -> None:
        if self._interactive:
            # WHY pad: a shorter line must fully cover the longer one it rewrites.
            self._stream.write("\r" + text.ljust(self._width))
            self._width = len(text)
            if final:
                self._stream.write("\n")
        else:
            self._stream.write(text + "\n")
        self._stream.flush()


class _Notebook:
    def __init__(self) -> None:
        from IPython.display import HTML, display

        self._html = HTML
        self._handle = display(HTML(_card("preparing…", None)), display_id=True)

    def preparing(self, origin: str) -> None:
        self._show(f"Community cache · preparing to pull from {html.escape(origin)}…", None)

    def update(self, snapshot: Snapshot) -> None:
        self._show(
            f"Community cache · pulling from {html.escape(snapshot.origin)}<br>"
            f"{html.escape(_progress_text(snapshot))}",
            snapshot.fraction,
        )

    def finished(self, snapshot: Snapshot, result: PullResult) -> None:
        self._show(
            f"Community cache · ✓ {result.rows_read:,} rows read · {result.rows_added:,} added · "
            f"{_duration(snapshot.elapsed_s)}",
            1.0,
        )

    def stopped(self, snapshot: Snapshot, reason: str) -> None:
        self._show(
            f"Community cache · stopped after {snapshot.rows_read:,} rows "
            f"({snapshot.rows_added:,} added): {html.escape(reason)}<br>"
            "Call <code>pull_from_remote()</code> again to continue.",
            snapshot.fraction,
        )

    def _show(self, body: str, fraction: float | None) -> None:
        if self._handle is not None:
            self._handle.update(self._html(_card(body, fraction)))


def reporter(requested: bool | None, *, stream: TextIO | None = None) -> Reporter:
    from screamingface._environment import ipykernel_loaded

    selected = sys.stderr if stream is None else stream
    in_notebook = ipykernel_loaded()
    interactive = selected.isatty()
    if requested is False or (requested is None and not (in_notebook or interactive)):
        return _Silent()
    if in_notebook:
        try:
            return _Notebook()
        except ImportError:
            pass
    return _Terminal(selected, interactive=interactive)


def _progress_text(snapshot: Snapshot) -> str:
    parts: list[str] = []
    fraction = snapshot.fraction
    if fraction is not None and snapshot.total is not None:
        filled = round(fraction * _BAR_WIDTH)
        parts.append(f"{'█' * filled}{'░' * (_BAR_WIDTH - filled)}  {fraction:4.0%}")
        parts.append(f"{snapshot.rows_read:,}/{snapshot.total:,} rows")
    else:
        parts.append(f"{snapshot.rows_read:,} rows")
    parts.append(f"{snapshot.rows_added:,} added")
    parts.append(_megabytes(snapshot.bytes_received))
    eta = snapshot.eta_s
    if eta is not None:
        parts.append(f"ETA {_duration(eta)}")
    return " · ".join(parts)


def _megabytes(count: int) -> str:
    return f"{count / 1_000_000:.0f} MB" if count >= 1_000_000 else f"{count / 1_000:.0f} kB"


def _duration(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}m{whole % 60:02d}s" if whole >= 60 else f"{whole}s"


def _card(body: str, fraction: float | None) -> str:
    # WHY the shared tokens and theme rules: the card follows the light / dark notebook theme like
    # every other SDK panel (`_ui/style.py`), and NO_MATH keeps MathJax off its text.
    from screamingface._ui.style import _DARK, _LIGHT, NO_MATH, _theme_rules

    style = (
        "<style>"
        f".sf-cache-pull{{{_LIGHT}}}"
        f"{_theme_rules('.sf-cache-pull', _LIGHT, _DARK)}"
        ".sf-cache-pull{max-width:640px;padding:8px 12px;color:var(--sf-ink);"
        "background:var(--sf-surface);border:1px solid var(--sf-line);"
        "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:13px;"
        "line-height:1.45}"
        ".sf-cache-pull__track{height:4px;margin-top:6px;background:var(--sf-surface-2)}"
        ".sf-cache-pull__fill{height:4px;background:var(--sf-accent)}"
        "</style>"
    )
    bar = ""
    if fraction is not None:
        bar = (
            "<div class='sf-cache-pull__track'>"
            f"<div class='sf-cache-pull__fill' style='width:{fraction * 100:.1f}%'></div></div>"
        )
    return f"{style}<div class='sf-cache-pull {NO_MATH}' role='status'>{body}{bar}</div>"


__all__ = ["Reporter", "Snapshot", "reporter"]
