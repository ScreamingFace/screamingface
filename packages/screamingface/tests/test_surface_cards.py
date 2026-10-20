"""The cards of the new surface: a block card and a chain card (E4b surface unit 6, DS-1).

FEATURE (rebuild-display §3, erratum E5): a closed block shows as a card with the kicker
``fanout`` and the sections ``members``, ``signals`` and ``steps``, where each step names its
category (judge, narrow, reduce, write). A chain shows as a card with the kicker ``chain`` and its
``stages``; a block stage shows as a ``fanout block``. Today's cards do not change, and a chain as
a member of today's Fusion no longer breaks today's card.
STORY: as a researcher in a notebook, the value I built with ``>>`` shows its blocks and steps
with the words I wrote.
INVARIANT defended: the golden HTML of a block with a judge, a narrow step and a reducer, and of a
chain with a block stage, stays byte-equal; every text from a value is escaped.

Regenerate the goldens from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_surface_cards as m; m.write_goldens()"
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import screamingface as sf
from screamingface import _surface as sx
from screamingface._surface.chain import _Block
from screamingface._ui.card_style import CARD_STYLE
from screamingface._ui.cards import block_card_html, chain_card_html

_GOLDENS = Path(__file__).parent / "data" / "surface_cards"


def _judged_block() -> sx.Pipeline:
    return (
        sx.Fanout(["prov/alpha", "prov/beta"], signals={"conf": sf.Verbalized("C: ([0-9]+)")})
        >> sx.Judge("prov/judge", rubric="Score <each> draft.")
        >> sx.Filter(where=sx.signal("score:judge") >= 5)
        >> sx.Vote(weights="score:judge")
    )


def _chain() -> sx.Pipeline:
    return (
        sf.Model("prov/planner")
        >> sx.Fanout(["prov/alpha", "prov/beta"])
        >> sx.Rank(1, by="cost_usd")
        >> sx.Synthesize("prov/writer", prompt="Write it.")
    )


def _block_of(chain: sx.Pipeline) -> _Block:
    (block,) = chain._stages
    assert isinstance(block, _Block)
    return block


_CARDS: dict[str, Callable[[], str]] = {
    "block_judge_narrow_vote": lambda: block_card_html(_block_of(_judged_block())),
    "chain_model_then_block": lambda: chain_card_html(_chain()),
}


def _body(name: str) -> str:
    """The card without the shared style sheet: the golden pins the card, not the house CSS."""

    card = _CARDS[name]()
    assert card.startswith(CARD_STYLE)
    return card.removeprefix(CARD_STYLE)


def write_goldens() -> None:
    _GOLDENS.mkdir(parents=True, exist_ok=True)
    for name in _CARDS:
        (_GOLDENS / f"{name}.html").write_text(_body(name) + "\n", encoding="utf-8")


@pytest.mark.parametrize("name", sorted(_CARDS))
def test_ds1_the_card_matches_its_golden(name: str) -> None:
    golden = _GOLDENS / f"{name}.html"
    assert golden.exists(), f"surface_cards/{name}.html is missing - run write_goldens()"

    assert _body(name) == golden.read_text(encoding="utf-8").removesuffix("\n")


def test_ds1_a_block_card_names_each_step_with_its_category() -> None:
    html = block_card_html(_block_of(_judged_block()))

    assert "<span class='sf-card__kicker'>fanout</span>" in html
    for title in ("members", "signals", "steps"):
        assert f"<div class='sf-section__title'>{title}</div>" in html
    for category in ("judge", "narrow", "reduce"):
        assert f"<div class='sf-detail__index'>{category}</div>" in html
    # every text from the value is escaped
    assert "Score &lt;each&gt; draft." in html
    assert "<each>" not in html
    assert "synthesizer" not in html


def test_ds1_a_chain_card_shows_a_block_stage_as_a_fanout_block() -> None:
    html = chain_card_html(_chain())

    assert "<span class='sf-card__kicker sf-card__kicker--pipeline'>chain</span>" in html
    assert "<div class='sf-detail__index'>stage 2</div>" in html
    assert "fanout block" in html


def test_ds1_a_writer_step_has_the_write_category() -> None:
    html = block_card_html(_block_of(sx.Fanout(["prov/a", "prov/b"]) >> sx.Synthesize("prov/w")))

    assert "<div class='sf-detail__index'>write</div>" in html


def test_ds1_a_one_block_chain_shows_its_block_card() -> None:
    chain = sx.Fanout(["prov/a", "prov/b"]) >> sx.Vote()

    assert chain._repr_html_() == block_card_html(_block_of(chain))


def test_ds1_a_longer_chain_shows_its_chain_card() -> None:
    chain = _chain()

    assert chain._repr_html_() == chain_card_html(chain)


@pytest.mark.parametrize(
    ("chain", "steps"),
    [
        (lambda: sx.Pipeline([sx.Fanout(["prov/a", "prov/b"])]), []),
        (
            lambda: sf.Model("prov/q") >> sx.Fanout(["prov/a", "prov/b"]) >> sx.Rank(1, by="p"),
            ["narrow"],
        ),
    ],
    ids=["fanout-only", "ends-in-narrow"],
)
def test_ds1_an_open_chain_card_shows_its_open_block(
    chain: Callable[[], sx.Pipeline], steps: list[str]
) -> None:
    html = chain_card_html(chain())

    assert "<div class='sf-card__hint'>open fanout block</div>" in html
    assert html.count("<div class='sf-detail__index'>narrow</div>") == len(steps)


def test_e5_a_chain_member_of_todays_fusion_shows_as_a_nested_chain() -> None:
    fusion = sf.Fusion(
        [sx.Fanout(["prov/a", "prov/b"]) >> sx.Vote(), "prov/c"], synthesizer="prov/w"
    )

    html = fusion._repr_html_()

    assert "<div class='sf-card__hint'>nested chain</div>" in html
    assert "<span class='sf-card__kicker'>fusion</span>" in html
