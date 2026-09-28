"""Sequence-like Client catalogues with optional notebook interactivity."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from typing import Any, overload

from screamingface._catalogue_vocabulary import (
    DECLARED_DIFFICULTY_TIERS,
    DECLARED_INTERACTION_TYPES,
)
from screamingface._ui.card_style import CARD_STYLE
from screamingface._ui.cards import (
    ALL_CHIP_VALUE,
    benchmark_tier_sections_html,
    benchmarks_rows_html,
    catalog_empty_html,
    catalog_html,
    difficulty_chip_options,
    interaction_chip_options,
    interaction_label,
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
    """FEATURE: the two-axis catalogue map (OME-1257) — clickable facet chips
    (Difficulty: easy / medium / hard · Interaction: single-shot / multi-turn /
    agentic · Origin: the origins present) over a listing grouped easy→hard with
    interaction lanes, and a per-row provenance chip (which carries the OME-1114
    ours/imported distinction and its source links). Every chip row leads with an
    All chip meaning "don't narrow on this axis"; clicking a chip regroups the
    listing to that facet, and the search box composes with the chips. The static
    fallback renders the full map as titled sections (it cannot click); a catalogue
    whose Engine predates the axis (no difficulty anywhere) keeps the familiar
    flat list.
    """

    _title = "Benchmarks"
    _aria = "ScreamingFace benchmark catalogue"
    _placeholder = "Filter benchmarks…"

    def _search_text(self, value: Benchmark) -> str:
        return f"{value.id} {value.title} {value.description}"

    def _rows(self, values: Sequence[Benchmark]) -> str:
        if not values or not _any_tier(values):
            return benchmarks_rows_html(values)
        return benchmark_tier_sections_html(
            tuple((tier, _interaction_lanes(records)) for tier, records in _tier_groups(values))
        )

    def _body(self, widgets: Any) -> tuple[Any, Callable[[str], None]]:
        difficulty_chips = widgets.ToggleButtons(
            options=difficulty_chip_options(), description="Difficulty:"
        )
        interaction_chips = widgets.ToggleButtons(
            options=interaction_chip_options(), description="Interaction:"
        )
        origin_chips = widgets.ToggleButtons(
            options=_origin_chip_options(self._values), description="Origin:"
        )
        rows = widgets.HTML()
        # WHY: 25+ boards would stretch the notebook cell to the full catalogue
        # height — the rows body scrolls after roughly a screenful instead, while
        # the search box and chips stay put above it (owner request, OME-1257).
        rows.add_class("sf-catalog__scroll")
        # The one piece of state the chips and the search box share: the live query.
        state: dict[str, str] = {"query": ""}

        def render() -> None:
            rows.value = self._facet_html(
                _chip_filter(difficulty_chips.value),
                _chip_filter(interaction_chips.value),
                _chip_filter(origin_chips.value),
                state["query"],
            )

        def refresh(query: str) -> None:
            state["query"] = query
            render()

        difficulty_chips.observe(lambda _change: render(), names="value")
        interaction_chips.observe(lambda _change: render(), names="value")
        origin_chips.observe(lambda _change: render(), names="value")
        render()
        body = widgets.VBox(children=(difficulty_chips, interaction_chips, origin_chips, rows))
        return body, refresh

    def _facet_html(
        self,
        difficulty: str | None,
        interaction: str | None,
        origin: str | None,
        query: str,
    ) -> str:
        """The listing under the current chip picks + search — always the same map.

        INVARIANT: chips FILTER what the map shows, they never change its shape —
        the surviving rows still render as tier sections with interaction lanes, so
        clicking "easy" reads as "the Easy shelf", not as a different view.
        """

        visible = tuple(
            value
            for value in self._values
            if self._matches(value, query)
            and (difficulty is None or value.difficulty == difficulty)
            and (interaction is None or value.interaction == interaction)
            and (origin is None or value.origin == origin)
        )
        if (
            not visible
            and interaction is not None
            and not any(value.interaction == interaction for value in self._values)
        ):
            # STORY: as a researcher clicking the Agentic chip today, I learn the
            # lane exists and is empty — not that my filter "broke".
            label = interaction_label(interaction).lower()
            return catalog_empty_html(
                f"No {label} benchmarks yet — this lane fills as {label} boards land."
            )
        return self._rows(visible)


def _chip_filter(value: str) -> str | None:
    """One chip pick → the filter it means: the All chip means 'no filter here'."""

    return None if value == ALL_CHIP_VALUE else value


def _origin_chip_options(
    values: Sequence[Benchmark],
) -> tuple[tuple[str, str], ...]:
    """(label, origin) pairs for the Origin chips — All first, our shelf next.

    WHY derived from the catalogue, not a fixed vocabulary: origin is an OPEN set by
    doctrine (OME-1114 — the SDK never validates it), so the honest chip set is the
    origins actually present: "screamingface" leads when present (our-shelf-first
    precedent), the rest follow in first-appearance order, and a newer Engine's new
    origin gets its own chip instead of becoming unreachable.
    """

    seen: list[str] = []
    for value in values:
        if value.origin not in seen:
            seen.append(value.origin)
    if "screamingface" in seen:
        seen.remove("screamingface")
        seen.insert(0, "screamingface")
    return (("All", ALL_CHIP_VALUE), *((origin_label(origin), origin) for origin in seen))


def _any_tier(values: Sequence[Benchmark]) -> bool:
    """Whether any board declares a difficulty — the map appears with the first one.

    WHY: an Engine predating OME-1257 serves no tiers at all; a lone "Unspecified"
    shelf over the whole catalogue would be noise pretending to be structure.
    """

    return any(value.difficulty is not None for value in values)


def _axis_groups(
    values: Sequence[Benchmark],
    key: Callable[[Benchmark], str | None],
    declared: tuple[str, ...],
) -> tuple[tuple[str | None, tuple[Benchmark, ...]], ...]:
    """Group boards along one declared axis: declared order, then unknown, None last.

    WHY this order: the declared tuple is the axis's reading direction (easy→hard
    for tiers); an unknown value from a newer Engine follows in first-appearance
    order rather than being refused; boards that never declared gather at the end.
    """

    order: list[str | None] = []
    groups: dict[str | None, list[Benchmark]] = {}
    for value in values:
        group_key: str | None = key(value)
        if group_key not in groups:
            order.append(group_key)
            groups[group_key] = []
        groups[group_key].append(value)
    ordered: list[str | None] = [known for known in declared if known in groups]
    ordered.extend(item for item in order if item not in ordered and item is not None)
    if None in groups:
        ordered.append(None)
    return tuple((group_key, tuple(groups[group_key])) for group_key in ordered)


def _tier_groups(
    values: Sequence[Benchmark],
) -> tuple[tuple[str | None, tuple[Benchmark, ...]], ...]:
    return _axis_groups(values, lambda value: value.difficulty, DECLARED_DIFFICULTY_TIERS)


def _interaction_lanes(
    values: Sequence[Benchmark],
) -> tuple[tuple[str | None, tuple[Benchmark, ...]], ...]:
    return _axis_groups(values, lambda value: value.interaction, DECLARED_INTERACTION_TYPES)


__all__: list[str] = []
