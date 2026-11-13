# pyright: reportMissingImports=false
# WHY file-level: the catalogue assembles through inspect_ai and inspect_evals, absent in the
# extra-less typecheck install.
"""A Benchmark page mentions Draft Feedback only when the Benchmark offers it.

FEATURE: Benchmark page prose. Draft Feedback is a Benchmark's mid-run answer to "is this draft
good enough yet?", which a Corrective Loop recipe asks for; a Benchmark without the offer
refuses such a recipe before any money moves. Not offering it is the default (95 of 96 rows),
so a page saying "no mid-run check" is noise, and a page saying a corrective loop is
"legitimate" where none is offered misleads. Only the page of a Benchmark that offers it says
so (today ifeval, the owner's one exception, OME-1513).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.definition import Benchmark  # noqa: E402
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT  # noqa: E402
from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    imported_benchmark,
)

#: Every way a page has talked about Draft Feedback: the glossary term, the retired "check
#: surface", the mid-run check, the attack it guards against, and the recipe that uses it.
_MENTION: re.Pattern[str] = re.compile(
    r"draft feedback|check surface|mid-run|elimination attack|corrective loop", re.IGNORECASE
)


def _pages() -> list[Benchmark]:
    """Every catalogue Benchmark plus the hand-built medxpert, as their pages publish them."""

    return [imported_benchmark(spec.key).benchmark for spec in BENCHMARKS] + [MEDXPERT]


@pytest.mark.parametrize("benchmark", _pages(), ids=lambda benchmark: benchmark.id)
def test_a_page_mentions_draft_feedback_exactly_when_it_offers_it(benchmark: Benchmark) -> None:
    """INVARIANT: the page and the offer agree, so a submitter never plans a loop it refuses."""

    mentions: bool = _MENTION.search(benchmark.description) is not None

    assert mentions == (benchmark.check_surface is not None)


def test_the_one_offering_page_names_draft_feedback() -> None:
    """The offer is stated in the glossary's words, not the retired 'check surface'."""

    offering: list[Benchmark] = [page for page in _pages() if page.check_surface is not None]

    assert [page.id for page in offering] == ["ifeval"]
    assert "Draft Feedback" in offering[0].description
