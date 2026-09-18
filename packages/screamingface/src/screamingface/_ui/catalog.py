"""Sequence-like Client catalogues with optional notebook interactivity."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from typing import Any, overload

from screamingface._ui.card_style import CARD_STYLE
from screamingface._ui.cards import (
    benchmark_origin_panel_html,
    benchmark_origin_sections_html,
    benchmarks_rows_html,
    catalog_html,
    models_rows_html,
    origin_label,
)
from screamingface._ui.style import NO_MATH_CLASSES
from screamingface.discovery import Benchmark, ModelInfo


class _Catalog[T](Sequence[T], ABC):
    """Immutable data value; notebook filtering lives only in a rendered widget."""

    __slots__ = ("_values",)

    _title: str
    _aria: str
    _placeholder: str

    def __init__(self, values: Sequence[T]) -> None:
        self._values = tuple(values)

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[T]:
        return iter(self._values)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T, ...]: ...

    def __getitem__(self, index: int | slice) -> T | tuple[T, ...]:
        return self._values[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _Catalog):
            return self._values == other._values
        if isinstance(other, tuple):
            return self._values == other
        return False

    def __repr__(self) -> str:
        return f"{self._title}({len(self)})"

    def _repr_html_(self) -> str:
        return catalog_html(self._title, self._aria, len(self), self._rows(self._values))

    def _ipython_display_(self) -> None:
        from IPython.display import HTML, display

        try:
            display(self._widget())
        except ImportError:
            display(HTML(self._repr_html_()))

    def _widget(self) -> Any:
        try:
            import ipywidgets as widgets
        except ImportError as exc:
            raise ImportError(
                "Install screamingface[notebook] for interactive catalogue search."
            ) from exc

        header = widgets.HTML(
            value=(
                f"{CARD_STYLE}<div class='sf-card__accent sf-card__accent--solid'></div>"
                "<div class='sf-catalog__head'>"
                f"<div class='sf-catalog__title'>{self._title}</div>"
                f"<div class='sf-catalog__count'>{len(self)}</div></div>"
            )
        )
        search = widgets.Text(placeholder=self._placeholder)
        body, refresh = self._body(widgets)

        def on_change(change: dict[str, Any]) -> None:
            refresh(str(change["new"]).strip().casefold())

        search.observe(on_change, names="value")
        root = widgets.VBox(children=(header, search, body))
        root.add_class("sf-ui")
        root.add_class("sf-catalog-widget")
        root.add_class("sf-catalog")
        for css_class in NO_MATH_CLASSES:
            root.add_class(css_class)
        return root

    def _body(self, widgets: Any) -> tuple[Any, Callable[[str], None]]:
        """One flat searchable HTML body; catalogues with structure override this."""

        body = widgets.HTML(value=self._rows(self._values))

        def refresh(query: str) -> None:
            visible = tuple(value for value in self._values if self._matches(value, query))
            body.value = self._rows(visible)

        return body, refresh

    def _matches(self, value: T, query: str) -> bool:
        return not query or query in self._search_text(value).casefold()

    @abstractmethod
    def _search_text(self, value: T) -> str:
        """Return searchable real fields for one record."""

    @abstractmethod
    def _rows(self, values: Sequence[T]) -> str:
        """Render escaped rows for one catalogue kind."""


class _ModelCatalog(_Catalog[ModelInfo]):
    _title = "Models"
    _aria = "ScreamingFace model catalogue"
    _placeholder = "Filter models…"

    def _search_text(self, value: ModelInfo) -> str:
        return f"{value.id} {value.provider}"

    def _rows(self, values: Sequence[ModelInfo]) -> str:
        return models_rows_html(values)


class _BenchmarkCatalog(_Catalog[Benchmark]):
    """FEATURE: benchmark provenance tabs (OME-1114) — one tab per origin, each
    linking to its source collection; the static fallback renders the same
    grouping as titled sections."""

    _title = "Benchmarks"
    _aria = "ScreamingFace benchmark catalogue"
    _placeholder = "Filter benchmarks…"

    def _search_text(self, value: Benchmark) -> str:
        return f"{value.id} {value.title} {value.description}"

    def _rows(self, values: Sequence[Benchmark]) -> str:
        if not values:
            return benchmarks_rows_html(values)
        return benchmark_origin_sections_html(_origin_groups(values))

    def _body(self, widgets: Any) -> tuple[Any, Callable[[str], None]]:
        groups = _origin_groups(self._values)
        if not groups:
            return super()._body(widgets)
        panels = tuple(
            widgets.HTML(value=benchmark_origin_panel_html(origin, records))
            for origin, records in groups
        )
        tabs = widgets.Tab(children=panels)
        for index, (origin, _) in enumerate(groups):
            tabs.set_title(index, origin_label(origin))

        def refresh(query: str) -> None:
            # INVARIANT: filtering hides rows inside each tab; the tabs themselves
            # stay, so provenance structure never flickers away while typing.
            for panel, (origin, records) in zip(panels, groups, strict=True):
                visible = tuple(record for record in records if self._matches(record, query))
                panel.value = benchmark_origin_panel_html(origin, visible)

        return tabs, refresh


def _origin_groups(
    values: Sequence[Benchmark],
) -> tuple[tuple[str, tuple[Benchmark, ...]], ...]:
    """Group benchmarks by origin — our shelf first, then first-appearance order."""

    order: list[str] = []
    groups: dict[str, list[Benchmark]] = {}
    for value in values:
        if value.origin not in groups:
            order.append(value.origin)
            groups[value.origin] = []
        groups[value.origin].append(value)
    # WHY: deterministic display regardless of wire order — the reader always
    # finds our boards in the first tab when any are present.
    if "screamingface" in groups:
        order.remove("screamingface")
        order.insert(0, "screamingface")
    return tuple((origin, tuple(groups[origin])) for origin in order)


__all__: list[str] = []
