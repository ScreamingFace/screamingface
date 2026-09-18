"""Every notebook panel root opts out of the page's maths typesetter.

INVARIANT: panels are transcripts, never formulas — the notebook must never typeset their
contents as maths. A prompt that mentions money carries literal `$` characters; HTML
escaping leaves them alone (`$` is not HTML-special), and MathJax then runs as a separate
pass over the already-rendered DOM, pairs the dollars up, and re-typesets the sentence
between them as inline maths — italic, with every space deleted. The only defence at that
layer is the typesetter's own opt-out class on the panel root, which makes it skip the whole
subtree. Two names because two major versions are in the wild (OME-1226).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

import screamingface as sf
from screamingface._notices import ClientNotice
from screamingface._ui.cards import catalog_html
from screamingface._ui.catalog import _ModelCatalog
from screamingface._ui.connection_state import _ConnectionPanelState
from screamingface._ui.connection_view import static_panel_html
from screamingface._ui.leaderboard_view import leaderboard_catalog_html
from screamingface._ui.notice_view import client_notice_html
from screamingface._ui.score_view import leaderboard_score_html
from screamingface._ui.style import NO_MATH, NO_MATH_CLASSES

_WHEN = datetime(2026, 9, 18, 10, tzinfo=UTC)

# The GSM8K instruction text that exposed this: three dollar signs, two of which pair up.
_MONEY_PROMPT = (
    "ANSWER: $ANSWER (without quotes) where $ANSWER is the answer. "
    "Janet sells the duck eggs for $2 per fresh duck egg."
)


def _root_classes(html: str) -> list[str]:
    """The class list of the first element after the panel's embedded stylesheet."""

    markup = html[html.rindex("</style>") :]
    match = re.search(r"<div class='([^']*)'", markup)
    assert match is not None, "the panel emitted no root element"
    return match.group(1).split()


def _score() -> sf.LeaderboardScore:
    return sf.LeaderboardScore(
        id=UUID("00000000-0000-4000-8000-000000000001"),
        version=1,
        benchmark_id="draco",
        spec_id="fusion/alpha",
        url4=sf.Url4("(@)!'a candidate'"),
        submitted_by=None,
        submitted_at=_WHEN,
        score=0.9,
        total_questions=10,
        correct_questions=9,
        ran_with_providers=("openrouter",),
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=False,
        metadata=None,
    )


def _leaderboard() -> sf.Leaderboard:
    return sf.Leaderboard(
        benchmark=sf.LeaderboardInfo(
            id="draco",
            display_name="DRACO",
            # WHY money in the description: a Leaderboard root carries untrusted benchmark
            # prose and does NOT carry `sf-ui`, so it is the easiest root to miss.
            description=f"Grading costs about {_MONEY_PROMPT}",
            dataset_url=None,
            created_at=_WHEN,
        ),
        entries=(),
        baselines=(),
    )


def _model_details() -> sf.ModelDetails:
    return sf.ModelDetails(
        id="openrouter/openai/gpt-5.5",
        provider="openrouter",
        upstream_id="openai/gpt-5.5",
        contract_id="pc_fixture",
        scope="account_profile",
        auth_mode="api_key",
        context_revision="ctx_fixture",
        source_revision=None,
        parameters={},
        tools={},
        transport={},
        observed_at=_WHEN,
        expires_at=datetime(2026, 9, 18, 10, 5, tzinfo=UTC),
        stale=False,
        degraded=False,
    )


def _connections_panel() -> str:
    state = _ConnectionPanelState(
        hosted=False,
        engine_url="http://127.0.0.1:9108",
        provider_mutations_enabled=True,
    )
    return static_panel_html(
        "http://127.0.0.1:9108",
        state,
        authenticated=False,
        authenticating=False,
    )


def _benchmark() -> sf.Benchmark:
    return sf.Benchmark(
        id="inspect-gsm8k",
        title="GSM8K",
        description=_MONEY_PROMPT,
        revision="74c94830e8de6afd",
        case_count=8,
    )


def _client_card() -> str:
    client = sf.Client(engine_url="http://127.0.0.1:9108")
    try:
        return cast(Any, client)._repr_html_()
    finally:
        client.close()


def _panels() -> list[tuple[str, str]]:
    """Every panel root that renders untrusted transcript text, by its own public path."""

    opus = sf.Model("provider/opus", name="opus")
    return [
        ("published score", leaderboard_score_html(_score())),
        ("connections", _connections_panel()),
        ("model card", cast(Any, opus)._repr_html_()),
        (
            "fusion card",
            cast(Any, sf.Fusion([opus, "provider/sonnet"], synthesizer=opus))._repr_html_(),
        ),
        ("pipeline card", cast(Any, sf.Pipeline([opus, "provider/sonnet"]))._repr_html_()),
        ("benchmark card", cast(Any, _benchmark())._repr_html_()),
        ("model details card", cast(Any, _model_details())._repr_html_()),
        ("client card", _client_card()),
        ("catalog", catalog_html("Models", "ScreamingFace models", 0, "")),
        ("leaderboard catalog", leaderboard_catalog_html(())),
        ("leaderboard board", cast(Any, _leaderboard())._repr_html_()),
        (
            "warning notice",
            client_notice_html(
                ClientNotice(
                    code="fixture_warning",
                    severity="warning",
                    title="Spend cap reached",
                    body=_MONEY_PROMPT,
                )
            ),
        ),
        (
            "info notice",
            client_notice_html(
                ClientNotice(
                    code="fixture_info",
                    severity="info",
                    title="Run complete",
                    body=_MONEY_PROMPT,
                )
            ),
        ),
    ]


_PANELS = _panels()
_PANEL_IDS = [name for name, _ in _PANELS]


@pytest.mark.parametrize(("name", "html"), _PANELS, ids=_PANEL_IDS)
def test_every_rendered_panel_root_opts_out_of_maths_typesetting(name: str, html: str) -> None:
    classes = _root_classes(html)

    # INVARIANT: both names, because two MathJax majors are in the wild — `mathjax_ignore`
    # (MathJax 3 · JupyterLab 4) and `tex2jax_ignore` (MathJax 2 · classic notebook and
    # nbconvert output). Dropping either silently re-breaks one of them.
    assert set(NO_MATH_CLASSES) <= set(classes), f"{name} would be typeset as maths"


@pytest.mark.parametrize(("name", "html"), _PANELS, ids=_PANEL_IDS)
def test_the_shared_theme_class_stays_first_on_a_panel_root(name: str, html: str) -> None:
    # WHY: the opt-out classes are APPENDED, never prepended. Two suites slice a rendered
    # document with `html.index("<div class='sf-ui")`, so the leading class is load-bearing
    # markup, not cosmetics.
    classes = _root_classes(html)

    assert classes[0] in {"sf-ui", "sf-lb", "sf-notice"}, f"{name} reordered its root classes"


def test_a_money_prompt_survives_the_panel_verbatim() -> None:
    html = client_notice_html(
        ClientNotice(
            code="fixture_info",
            severity="info",
            title="Prompt",
            body=_MONEY_PROMPT,
        )
    )

    # The characters were never the problem — escaping already leaves `$` alone. What the
    # opt-out buys is that the browser stops re-typesetting the text around them.
    assert _MONEY_PROMPT in html
    assert set(NO_MATH_CLASSES) <= set(_root_classes(html))


def test_the_catalogue_widget_root_opts_out_of_maths_typesetting() -> None:
    root = _ModelCatalog(())._widget()

    assert set(NO_MATH_CLASSES) <= set(root._dom_classes)


def test_the_connection_panel_widget_root_opts_out_of_maths_typesetting() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return ()

    class LocalClient:
        engine_url = "http://127.0.0.1:9108"
        authenticated = False
        authenticating = False
        connections = Connections()

    panel = sf.ConnectionPanel(cast(Any, LocalClient()))
    root = panel.widget()
    try:
        assert set(NO_MATH_CLASSES) <= set(cast(Any, root)._dom_classes)
    finally:
        root.close()


def test_the_opt_out_string_and_tuple_stay_in_step() -> None:
    # WHY both forms: HTML roots interpolate the joined string into a `class='…'`
    # attribute; ipywidgets roots call `add_class` once per name. One source of truth.
    assert NO_MATH.split() == list(NO_MATH_CLASSES)
