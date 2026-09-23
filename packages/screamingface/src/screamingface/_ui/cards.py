"""Escaped notebook HTML for Client authoring values and catalogues."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import TYPE_CHECKING

from screamingface._catalogue_vocabulary import (
    DECLARED_DIFFICULTY_TIERS,
    DECLARED_INTERACTION_TYPES,
)
from screamingface._ui.card_style import CARD_STYLE
from screamingface._ui.engine_origin import _is_hosted_engine
from screamingface._ui.style import NO_MATH
from screamingface.recipe import _recipe_kind

if TYPE_CHECKING:
    from typing import Protocol

    from screamingface.discovery import Benchmark, ModelDetails, ModelInfo
    from screamingface.fusion import Fusion
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline
    from screamingface.recipe import Recipe

    class _ClientLike(Protocol):
        """The read-only surface the connection card renders (sync or async Client)."""

        @property
        def engine_url(self) -> str: ...
        @property
        def scoreboard_url(self) -> str: ...
        @property
        def closed(self) -> bool: ...
        @property
        def authenticated(self) -> bool: ...


def model_card_html(model: Model) -> str:
    """Render only authoring fields actually held by one Model."""

    fields = _field("route", _mono(model.model)) + _field(
        "provider", escape(_provider_of(model.model))
    )
    if model.prompt is not None:
        fields += _field("prompt", escape(model.prompt), wide=True)
    if model.params:
        fields += _field("params", _params(model.params), wide=True)
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' aria-label='ScreamingFace model'>"
        "<div class='sf-card__accent sf-card__accent--solid'></div>"
        f"<div class='sf-card__head'><span class='sf-card__title'>{escape(model.name)}</span>"
        "<span class='sf-card__kicker'>model</span></div>"
        f"<div class='sf-card__grid'>{fields}</div></div>"
    )


def fusion_card_html(fusion: Fusion) -> str:
    """Render the Benchmark-independent Fusion topology."""

    members = "".join(_member_detail(member) for member in fusion.members)
    synthesis = ""
    if fusion.synthesizer is not None:
        fields = _synthesizer_fields(fusion.synthesizer)
        synthesis = _section("synthesis", f"<div class='sf-card__grid'>{fields}</div>")
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' aria-label='ScreamingFace fusion'>"
        "<div class='sf-card__accent'></div>"
        f"<div class='sf-card__head'><span class='sf-card__title'>{escape(fusion.name)}</span>"
        "<span class='sf-card__kicker'>fusion</span></div>"
        f"{_section('members', members)}{synthesis}</div>"
    )


def pipeline_card_html(pipeline: Pipeline) -> str:
    """Render one serial Candidate as an explicitly ordered topology."""

    stages = "".join(
        _recipe_detail(stage, index=index) for index, stage in enumerate(pipeline.stages, start=1)
    )
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' aria-label='ScreamingFace pipeline'>"
        "<div class='sf-card__accent sf-card__accent--pipeline'></div>"
        f"<div class='sf-card__head'><span class='sf-card__title'>{escape(pipeline.name)}</span>"
        "<span class='sf-card__kicker sf-card__kicker--pipeline'>pipeline</span></div>"
        f"{_section('stages', stages)}</div>"
    )


def models_rows_html(records: Sequence[ModelInfo]) -> str:
    if not records:
        return "<div class='sf-catalog__empty'>No models match.</div>"
    return "".join(
        "<div class='sf-catalog__row'>"
        f"<div class='sf-catalog__id'>{escape(record.id)}</div>"
        f"{_tags(_chip(record.provider))}</div>"
        for record in records
    )


# FEATURE: benchmark provenance (OME-1114) — origin → (label, source URL), shown as
# a per-row chip since the two-axis map landed (OME-1257).
# WHY SDK-side: pure presentation of one server field; the Engine ships no links.
# An origin absent from this map still renders — a plain chip named by the origin
# string, with no source link — so a newer Engine's new origin degrades gracefully.
_ORIGIN_SOURCES: Mapping[str, tuple[str, str]] = {
    "screamingface": ("ScreamingFace", "https://leaderboard.dev.screamingface.ai/"),
    "inspect_evals": ("inspect_evals", "https://ukgovernmentbeis.github.io/inspect_evals/"),
}


def origin_label(origin: str) -> str:
    """Human name for one origin; an unmapped origin names itself."""

    label, _ = _ORIGIN_SOURCES.get(origin, (origin, ""))
    return label


def origin_chip_html(origin: str) -> str:
    """One provenance chip per row — linked to its source collection when mapped.

    DON'T-REGRESS (OME-1114): the two-axis map (OME-1257) moved provenance from
    top-level tabs to this per-row chip; the ours/imported distinction AND the
    source-collection links must stay visible in the listing.
    """

    label, url = _ORIGIN_SOURCES.get(origin, (origin, ""))
    if not url:
        return f"<span class='sf-chip'>{escape(label)}</span>"
    return (
        f"<a class='sf-chip' href='{escape(url)}' target='_blank' "
        f"rel='noopener'>{escape(label)}</a>"
    )


# FEATURE: the two-axis catalogue map (OME-1257) — tier → (shelf title, one-line
# tagline teaching what the shelf means). WHY SDK-side: pure presentation of one
# server field, ordered by the shared vocabulary; the Engine ships no display text.
# A tier absent from this map still renders — its own trailing shelf, named by the
# Engine's word verbatim — so a newer Engine's new tier degrades gracefully.
_TIER_PRESENTATION: Mapping[str, tuple[str, str]] = {
    "easy": (
        "Easy",
        "Warm-up boards — material frontier models largely saturate; quick, cheap signal.",
    ),
    "medium": (
        "Medium",
        "Real headroom without expert stakes — knowledge exams, instruction following.",
    ),
    "hard": (
        "Hard",
        "Expert-written work today's best models visibly fail — where fusion gains matter most.",
    ),
}
# The tier value the listing shows for a board whose Engine predates difficulty tiers.
UNSPECIFIED_TIER_LABEL = "Unspecified"
_INTERACTION_LABELS: Mapping[str, str] = {
    "single_shot": "Single-shot",
    "multi_turn": "Multi-turn",
    "agentic": "Agentic",
}
# AIDEV-NOTE: "agentic" is a PRESENTATION-ONLY chip today — the Engine declares no such
# interaction value yet (its InteractionType comment says agentic shapes arrive later).
# The chip advertises the axis's future; reconcile this spelling with the Engine's when
# the real declared value lands, and the conformance pin stays on the DECLARED tuples.
_UPCOMING_INTERACTIONS: tuple[str, ...] = ("agentic",)
_UNDECLARED_INTERACTION_LABEL = "Undeclared interaction"


def tier_label(tier: str | None) -> str:
    """Shelf title for one tier; None means an Engine that never declared one."""

    if tier is None:
        return UNSPECIFIED_TIER_LABEL
    label, _ = _TIER_PRESENTATION.get(tier, (tier, ""))
    return label


def _tier_tagline_html(tier: str | None) -> str:
    if tier is None:
        return (
            "<div class='sf-card__hint'>Boards from an Engine that predates difficulty tiers.</div>"
        )
    _, tagline = _TIER_PRESENTATION.get(tier, (tier, ""))
    if not tagline:
        return ""
    return f"<div class='sf-card__hint'>{escape(tagline)}</div>"


def interaction_label(interaction: str | None) -> str:
    """Lane title for one interaction shape; an unmapped shape names itself."""

    if interaction is None:
        return _UNDECLARED_INTERACTION_LABEL
    return _INTERACTION_LABELS.get(interaction, interaction)


# The All chip's value on every axis row — meaning "no filter on this axis".
# INVARIANT: a REAL value, never Python None — ipywidgets treats a None value as
# "no selection" and clears every button highlight, so an All chip valued None
# filters correctly on click but only LOOKS selected on a second click. No wire
# vocabulary can collide: difficulty/interaction are closed sets without "all",
# and an origin literally named "all" would shadow only its own chip label.
ALL_CHIP_VALUE = "all"


def difficulty_chip_options() -> tuple[tuple[str, str], ...]:
    """(label, wire value) pairs for the widget's Difficulty chips — All first.

    FEATURE: clickable facet chips over the catalogue (OME-1257).
    """

    return (
        ("All", ALL_CHIP_VALUE),
        *((tier_label(tier), tier) for tier in DECLARED_DIFFICULTY_TIERS),
    )


def interaction_chip_options() -> tuple[tuple[str, str], ...]:
    """(label, wire value) pairs for the widget's Interaction chips — All first.

    WHY the upcoming values appear: an "Agentic" chip over an empty lane teaches the
    reader where agentic boards will land, exactly like the always-shown lane headers.
    """

    values: tuple[str, ...] = (*DECLARED_INTERACTION_TYPES, *_UPCOMING_INTERACTIONS)
    return (("All", ALL_CHIP_VALUE), *((interaction_label(value), value) for value in values))


def catalog_empty_html(message: str) -> str:
    """One escaped empty-state line for a catalogue body with nothing to show."""

    return f"<div class='sf-catalog__empty'>{escape(message)}</div>"


def benchmark_tier_panel_html(
    tier: str | None,
    lanes: Sequence[tuple[str | None, Sequence[Benchmark]]],
) -> str:
    """One shelf: the tier's tagline, then one interaction lane per group.

    WHY lanes render even as a single group: the interaction axis is half the map —
    showing "Single-shot" over today's boards teaches the reader where multi-turn
    and agentic lanes will appear as they land (OME-1257).
    """

    if not lanes:
        return _tier_tagline_html(tier) + benchmarks_rows_html(())
    # WHY the sub color: the lane header must read as SUBORDINATE to the tier title
    # above it — same mono small-caps register, one step softer ink (existing tokens
    # only; no new styles).
    body = "".join(
        "<div class='sf-section__title sf-catalog__sub'>"
        f"{escape(interaction_label(interaction))}</div>" + benchmarks_rows_html(records)
        for interaction, records in lanes
    )
    return _tier_tagline_html(tier) + body


def benchmark_tier_sections_html(
    sections: Sequence[tuple[str | None, Sequence[tuple[str | None, Sequence[Benchmark]]]]],
) -> str:
    """Static fallback for the tabbed map: one titled shelf per tier, easy→hard."""

    return "".join(
        _section(tier_label(tier), benchmark_tier_panel_html(tier, lanes))
        for tier, lanes in sections
    )


def benchmarks_rows_html(records: Sequence[Benchmark]) -> str:
    if not records:
        return "<div class='sf-catalog__empty'>No benchmarks match.</div>"
    return "".join(
        "<div class='sf-catalog__row'>"
        f"<div class='sf-catalog__id'>{escape(record.title)}</div>"
        + _tags(
            _chip(record.id) + _chip(f"{record.case_count} cases") + origin_chip_html(record.origin)
        )
        + f"<div class='sf-card__hint'>{escape(record.description)}</div></div>"
        for record in records
    )


def benchmark_card_html(benchmark: Benchmark) -> str:
    """Render the identity card a researcher reads before evaluating."""

    fields = (
        _field("id", _mono(benchmark.id))
        + _field("cases", escape(str(benchmark.case_count)))
        + _field("revision", _mono(benchmark.revision))
        + _field("origin", _origin_value_html(benchmark.origin))
        + _field("description", escape(benchmark.description), wide=True)
    )
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' aria-label='ScreamingFace benchmark'>"
        "<div class='sf-card__accent sf-card__accent--solid'></div>"
        f"<div class='sf-card__head'><span class='sf-card__title'>{escape(benchmark.title)}</span>"
        "<span class='sf-card__kicker'>benchmark</span></div>"
        f"<div class='sf-card__grid'>{fields}</div></div>"
    )


def model_details_card_html(details: ModelDetails) -> str:
    """Render only the profile fields actually held by one ModelDetails."""

    # WHY: freshness collapses to a single derived word — never a fabricated freshness metric.
    freshness = "degraded" if details.degraded else ("stale" if details.stale else "fresh")
    fields = (
        _field("id", _mono(details.id))
        + _field("provider", escape(details.provider))
        + _field("scope", escape(details.scope))
        + _field("auth", escape(details.auth_mode))
        + _field("parameters", escape(str(len(details.parameters))))
        + _field("tools", escape(str(len(details.tools))))
        + _field("transport", escape(str(len(details.transport))))
        + _field("freshness", escape(freshness))
    )
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' "
        "aria-label='ScreamingFace model details'>"
        "<div class='sf-card__accent sf-card__accent--solid'></div>"
        f"<div class='sf-card__head'><span class='sf-card__title'>{escape(details.id)}</span>"
        "<span class='sf-card__kicker'>model</span></div>"
        f"<div class='sf-card__grid'>{fields}</div></div>"
    )


def client_card_html(client: _ClientLike) -> str:
    """Render which Engine + Scoreboard a configured Client targets, plus local status chips.

    FEATURE: connection card — `sf.configure(...)`/`sf.Client(...)` render the origin they are
    wired to instead of the opaque default repr.
    """

    fields = _field("engine", _mono(client.engine_url)) + _field(
        "scoreboard", _mono(client.scoreboard_url)
    )
    status = _section("status", f"<div class='sf-chips'>{_status_chips(client)}</div>")
    return (
        f"{CARD_STYLE}<div class='sf-ui sf-card {NO_MATH}' aria-label='ScreamingFace client'>"
        "<div class='sf-card__accent sf-card__accent--solid'></div>"
        "<div class='sf-card__head'><span class='sf-card__title'>ScreamingFace</span>"
        "<span class='sf-card__kicker'>client</span></div>"
        f"<div class='sf-card__grid'>{fields}</div>{status}</div>"
    )


def catalog_html(title: str, aria: str, count: int, rows: str) -> str:
    """Wrap escaped rows in the static fallback used outside interactive notebooks."""

    return (
        f"{CARD_STYLE}<div class='sf-ui sf-catalog {NO_MATH}' aria-label='{escape(aria)}'>"
        "<div class='sf-card__accent sf-card__accent--solid'></div>"
        f"<div class='sf-catalog__head'><div class='sf-catalog__title'>{escape(title)}</div>"
        f"<div class='sf-catalog__count'>{count}</div></div>{rows}</div>"
    )


def _field(label: str, value_html: str, *, wide: bool = False) -> str:
    css = "sf-card__field wide" if wide else "sf-card__field"
    return (
        f"<div class='{css}'><div class='sf-card__k'>{escape(label)}</div>"
        f"<div class='sf-card__v'>{value_html}</div></div>"
    )


def _section(title: str, body: str) -> str:
    return (
        f"<div class='sf-section'><div class='sf-section__title'>{escape(title)}</div>{body}</div>"
    )


def _member_detail(member: Recipe) -> str:
    return _recipe_detail(member)


def _recipe_detail(recipe: Recipe, *, index: int | None = None) -> str:
    route = getattr(recipe, "model", None)
    kind = _recipe_kind(recipe)
    if route is None:
        detail = f"<div class='sf-card__hint'>nested {escape(kind)}</div>"
    else:
        detail = f"<div class='sf-detail__route'>{escape(str(route))}</div>"
    order = "" if index is None else f"<div class='sf-detail__index'>stage {index}</div>"
    return (
        "<div class='sf-detail__item'>"
        f"{order}<div class='sf-detail__name'>{escape(recipe.name)}</div>{detail}</div>"
    )


def _synthesizer_fields(recipe: Recipe) -> str:
    route = getattr(recipe, "model", None)
    if route is None:
        value = (
            f"<span class='sf-mono'>{escape(recipe.name)}</span>"
            f"<div class='sf-card__hint'>nested {escape(_recipe_kind(recipe))}</div>"
        )
        return _field("synthesizer", value, wide=True)

    fields = _field("synthesizer", _mono(str(route)), wide=True)
    prompt = getattr(recipe, "prompt", None)
    if prompt is not None:
        fields += _field("prompt", escape(str(prompt)), wide=True)
    params = getattr(recipe, "params", None)
    if params:
        fields += _field("params", _params(params), wide=True)
    return fields


def _provider_of(route: str) -> str:
    head = route.split("/", 1)[0]
    return head if head and head != route else "—"


def _origin_value_html(origin: str) -> str:
    """Origin as a link to its source collection when the map knows it."""

    _, url = _ORIGIN_SOURCES.get(origin, (origin, ""))
    if not url:
        return escape(origin)
    return f"<a href='{escape(url)}' target='_blank' rel='noopener'>{escape(origin)}</a>"


def _mono(value: str) -> str:
    return f"<span class='sf-mono'>{escape(value)}</span>"


def _params(values: Mapping[str, object]) -> str:
    return _mono(", ".join(f"{name}={value}" for name, value in values.items()))


def _chip(value: str) -> str:
    return f"<span class='sf-chip'>{escape(value)}</span>"


def _tags(chips: str) -> str:
    return f"<div class='sf-catalog__tags'>{chips}</div>"


def _status_chips(client: _ClientLike) -> str:
    # WHY: every chip is derived from local Client state — the card must never touch the
    # network to render (a repr runs on every notebook display).
    environment = "hosted" if _is_hosted_engine(client.engine_url) else "local"
    lifecycle = "closed" if client.closed else "open"
    authentication = "signed in" if client.authenticated else "not signed in"
    return "".join(_status_chip(text) for text in (environment, lifecycle, authentication))


def _status_chip(text: str) -> str:
    # WHY plain sf-chip: every card chip is neutral now — SFDS v2 rations gold to the
    # win, and no data chip is a win. The former --muted modifier became the base look.
    return f"<span class='sf-chip'>{escape(text)}</span>"


__all__: list[str] = []
